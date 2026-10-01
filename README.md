# mem0-mcp-wrapper

Give every MCP client on your network the **same long-term memory** your Open WebUI chats use.

A thin MCP (Model Context Protocol) wrapper around a self-hosted [mem0](https://github.com/mem0ai/mem0) REST API, plus the two other pieces of the stack it was built for:

```
┌──────────────┐     ┌───────────────┐     ┌─────────────────────────┐
│ MCP clients  │     │  mem0-mcp     │     │  mem0 REST API          │
│ Crush, etc.  │────▶│  (this repo,  │────▶│  mem0ai + FastAPI       │
│              │HTTP │   :8300/mcp)  │HTTP │      :8000              │
└──────────────┘     └───────────────┘     └──────────┬──────────────┘
                                                      │
┌──────────────┐                                      ▼
│ Open WebUI   │───────────────────────────────▶ ┌──────────┐
│ (memory      │        (same REST API)          │  Qdrant  │
│  filter)     │                                 │  + Ollama│
└──────────────┘                                 └──────────┘
```

- **One memory per user email**, shared by everything that talks to it.
- The MCP layer adds its own bearer token, so anything on the LAN can't read your memories without the secret.
- `mem0-mcp` is deliberately dumb: no vector store, no LLM calls of its own — all memory lives in the single mem0/Qdrant instance.

## Why this exists

Every other mem0 MCP server we could find targets the **hosted mem0 platform** or embeds its **own private vector store** — neither of which shares memory with a self-hosted Open WebUI. This wrapper speaks to a plain self-hosted mem0 REST API instead, so an Open WebUI filter and your CLI agents read and write the **same** Qdrant-backed memory.

## Repo contents

| Path | What it is |
|---|---|
| [`mcp-server/`](mcp-server/) | The MCP wrapper (streamable HTTP, bearer auth, 6 tools) |
| [`mem0-server/`](mem0-server/) | The mem0 REST API server (FastAPI + mem0ai + Ollama + Qdrant) |
| [`openwebui-filter/`](openwebui-filter/) | The Open WebUI Function (Filter) that injects/recalls memories in OWUI chats |
| [`examples/`](examples/) + [`docker-compose.yml`](docker-compose.yml) | A complete working deployment |

## Quick start (docker compose)

1. Create `secrets.env` (next to the compose file):

   ```bash
   # OLLAMA_API_KEY=<your-ollama-cloud-key>   # optional: fact extraction via Ollama Cloud
   MEM0_API_KEY=$(openssl rand -hex 24)       # mem0 REST API + MCP wrapper auth
   MEM0_MCP_TOKEN=$(openssl rand -hex 24)     # the MCP endpoint's own LAN bearer
   ```

   Without `OLLAMA_API_KEY` the mem0 server falls back to a local Ollama model for fact extraction.

2. `docker compose up -d --build`

3. Wire an MCP client at `http://<host>:8300/mcp` with header
   `Authorization: Bearer $MEM0_MCP_TOKEN`:

   ```bash
   # Crush (~/.config/crush/crushrc) — https://github.com/charmbracelet/crush
   mcp add mem0 --type http \
     --url "http://<host>:8300/mcp" \
     --header Authorization "Bearer $MEM0_MCP_TOKEN"

   # Claude Code / any streamable-HTTP MCP client:
   #   type: http, url: http://<host>:8300/mcp,
   #   headers: {Authorization: "Bearer <MEM0_MCP_TOKEN>"}
   ```

4. **Open WebUI**: Admin → Functions → new Function → paste
   [`openwebui-filter/openwebui_mem0_filter.py`](openwebui-filter/openwebui_mem0_filter.py),
   enable it globally (and/or per user). Set its `mem0_url` valve to
   `http://mem0:8000` (compose service name) and `mem0_api_key` to `$MEM0_API_KEY`.

Now a chat in Open WebUI and a Crush session on any machine see the same memories.

## MCP tools

| Tool | Notes |
|---|---|
| `search_memory(query, user_id?, top_k?, threshold?)` | Scored similarity search in the user's space |
| `add_memory(messages, user_id?, infer?)` | `messages` = JSON array of role/content; `infer: true` runs LLM fact extraction |
| `list_memories(user_id?, limit?)` | Everything stored for a user, newest first |
| `delete_memory(memory_id)` | Remove one memory (IDs come from search/list) |
| `delete_all_memories(user_id)` | Destructive; **refused** for the `MEM0_DEFAULT_USER` unless `MEM0_ALLOW_WIPE_DEFAULT=1` is set in the container |
| `mem0_health()` | Backend status: LLM + embedder in use |

## Configuration

### mcp-server

| Env | Default | Purpose |
|---|---|---|
| `MEM0_URL` | `http://mem0:8000` | The mem0 REST API base URL |
| `MEM0_API_KEY` | *(empty)* | Bearer sent to the mem0 REST API |
| `MCP_BEARER_TOKEN` | random per boot (logged) | The MCP endpoint's own required bearer |
| `MEM0_DEFAULT_USER` | *(empty)* | Default `user_id` for tools; keep empty to force explicit user ids |
| `MCP_PUBLIC_URL` | `http://localhost:8300` | Issuer/resource-server URL for mcp 2.x `AuthSettings` |
| `MEM0_ALLOW_WIPE_DEFAULT` | unset | Opt-in to allow wiping the default user's whole space |

### mem0-server

| Env | Default | Purpose |
|---|---|---|
| `MEM0_API_KEY` | *(empty)* | If set, every endpoint requires `Authorization: Bearer` |
| `OLLAMA_URL` | `http://ollama:11434` | Local Ollama (embeddings, fallback LLM) |
| `OLLAMA_API_KEY` | *(empty)* | If set, fact extraction goes through Ollama Cloud's OpenAI-compatible API |
| `OLLAMA_CLOUD_URL` | `https://ollama.com/v1` | Ollama Cloud base URL |
| `MEM0_LLM_MODEL` | `gemma4:31b` | Cloud fact-extraction model |
| `MEM0_LOCAL_LLM_MODEL` | `qwen3:4b-instruct` | Local fallback extraction model |
| `MEM0_EMBED_MODEL` | `nomic-embed-text` | Embedding model (local Ollama) |
| `MEM0_EMBED_DIMS` | `768` | Embedding dimensions |
| `QDRANT_HOST` | `qdrant` | Qdrant host |
| `MEM0_HISTORY_DB` | `/data/history.db` | SQLite chat-history sidecar |

### openwebui-filter (valves)

`mem0_url`, `mem0_api_key`, `user_id_field` (email|id), `top_k`, `threshold`,
`search_timeout` (seconds; search bursts serialize behind local embed loads),
`learn`, `show_status`, `priority`. Per-user override: `enabled`.

## Performance notes

- `add_memory` with `infer: true` runs an LLM call (~15–30 s via Ollama Cloud, slower locally).
- mem0 search latency is dominated by the embedding model. If several clients burst at once, they
  serialize behind Ollama's `OLLAMA_NUM_PARALLEL` slot — with a GPU squeezed by other workloads,
  embeddings can fall back to CPU (seconds per call). The OWUI filter's `search_timeout` valve
  (`default 60`) exists to ride that out.
- Watch out for `mem0ai` version drift: pin it (compose pins `2.2.1`).

## Security notes

- **Two separate secrets**: `MEM0_API_KEY` (REST API + wrapper) and `MCP_BEARER_TOKEN` (MCP clients). Keep the MCP one machine-local (`chmod 600`).
- Keep `mem0` and `qdrant` off the LAN (compose binds mem0 to `127.0.0.1`); only `mem0-mcp` listens on the network, and it requires the bearer.
- The `create_token`-style self-cloning risks in *your* automation layers are yours to watch — this repo only stores memories.

## License

MIT — see [LICENSE](LICENSE).