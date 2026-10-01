# mem0-mcp-wrapper

Give every MCP client on your network the **same long-term memory** — a locally hosted memory store everything can handle. No cloud accounts, no data leaving your machines: memories live in your own Qdrant, extracted by your own Ollama, served to anything that speaks MCP.

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

To run a **locally hosted version of memories** that everything can handle. The mem0 library is self-hostable (Qdrant + Ollama), but each MCP server around it bundles its **own private vector store** — a parallel memory that never meets the rest of your stack. This kit splits mem0 behind a plain REST API and exposes it three ways (MCP, REST, Open WebUI filter), so agents, chats, and scripts all read and write **one** Qdrant-backed memory per user.

## Repo contents

| Path | What it is |
|---|---|
| [`mcp-server/`](mcp-server/) | The MCP wrapper (streamable HTTP, bearer auth, 6 tools) |
| [`mem0-server/`](mem0-server/) | The mem0 REST API server (FastAPI + mem0ai + Ollama + Qdrant) |
| [`openwebui-filter/`](openwebui-filter/) | The Open WebUI Function (Filter) that injects/recalls memories in OWUI chats |
| [`examples/`](examples/) + [`docker-compose.yml`](docker-compose.yml) | A complete working deployment |

## Step-by-step deployment

### 1. Get the code

```bash
git clone https://github.com/rainyvalley/mem0-mcp-wrapper.git
cd mem0-mcp-wrapper
```

### 2. Create your secrets file

```bash
cp .env.example secrets.env
nano secrets.env            # or any editor
openssl rand -hex 24        # run twice: once per REQUIRED value
chmod 600 secrets.env
```

Fill in:
- `MEM0_API_KEY` — protects the mem0 REST API (the MCP wrapper and Open WebUI filter both send it)
- `MCP_BEARER_TOKEN` — protects the MCP endpoint itself (what MCP clients send)
- `OLLAMA_API_KEY` — optional; leave it commented to use your local Ollama model for fact extraction

### 3. Build and start the containers

```bash
docker compose up -d --build
```

What this builds and starts:

| Container | Built from | Role |
|---|---|---|
| `mem0` | `mem0-server/Dockerfile` | mem0 REST API on :8000 (host-only by default) |
| `mem0-mcp` | `mcp-server/Dockerfile` | MCP server on :8300 (LAN-reachable) |
| `qdrant` | official image | Vector store (no published ports — internal only) |
| `ollama` | official image | Embeddings local; fact extraction (cloud if `OLLAMA_API_KEY` set) |

### 4. Pull the models Ollama needs

```bash
docker exec ollama ollama pull nomic-embed-text   # embeddings (required)
docker exec ollama ollama pull qwen3:4b-instruct  # local fact extraction (skip if using cloud)
```

### 5. Verify

```bash
# mem0 REST health (LLM + embedder shown):
curl -s http://127.0.0.1:8000/health -H "Authorization: Bearer $(grep ^MEM0_API_KEY secrets.env | cut -d= -f2)"

# MCP endpoint alive (expect 200 + an SSE initialize response):
curl -s -X POST http://127.0.0.1:8300/mcp \
  -H "Authorization: Bearer $(grep ^MCP_BEARER_TOKEN secrets.env | cut -d= -f2)" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}'
```

Now integrate the clients you use:

- **Integrate with Crush** — section 6
- **Integrate with Open WebUI** — section 7
- Other MCP clients: [`examples/mcp-clients.md`](examples/mcp-clients.md)

---

### 6. Integrate with Crush (CLI agent)

Edit `~/.config/crush/crushrc` (Bash syntax) and add:

```bash
# resolve the token from a file so the secret never sits in the rc itself
MEM0_MCP_TOKEN="${MEM0_MCP_TOKEN:-$(sed -nE 's/^[[:space:]]*(export[[:space:]]+)?MEM0_MCP_TOKEN=["'"']?([^"'"'[:space:]*)["'"'[:space:]]*$/\2/p' "$HOME/.config/crush/ollama.env" 2>/dev/null | head -n1)}"

mcp add mem0 --type http \
  --url "http://<docker-host>:8300/mcp" \
  --header Authorization "Bearer $MEM0_MCP_TOKEN"
```

Put the token in place (create the file if needed):

```bash
printf 'MEM0_MCP_TOKEN=%s\n' "$(grep ^MCP_BEARER_TOKEN secrets.env | cut -d= -f2)" \
  >> ~/.config/crush/ollama.env
chmod 600 ~/.config/crush/ollama.env
```

Restart crush (a running TUI keeps its startup config). Verify inside the TUI with `/` (memory tools appear), or from bash:

```bash
crush run "search my memory for: favorite color"
```

Optional (Crush-side behavior config, in the same crushrc):
- The MCP server advertises instructions telling the agent to `search_memory` before answering user questions and to `add_memory` durable facts.
- `user_id`: pass the email-like id you also use in Open WebUI (see step 7) so both clients share one space.

### 7. Integrate with Open WebUI

**7a. Reach the mem0 API from Open WebUI**
- If Open WebUI runs in the **same docker compose** (or same docker network): the filter can use `http://mem0:8000` directly — the service name resolves inside the network.
- If Open WebUI runs elsewhere: publish mem0 on the LAN first. Replace the `ports:` line for `mem0` in `docker-compose.yml`:

  ```yaml
      ports:
        - "8000:8000"   # LAN-reachable; MEM0_API_KEY is still required on every call
  ```

  then `docker compose up -d mem0`. (The API key requirement is what keeps this safe.)

**7b. Register the filter (Function) in Open WebUI**

1. Open WebUI → sign in as **admin** → **Admin Panel** (bottom-left gear) → **Functions**.
2. Click **+** (new Function).
3. Give it any Name (e.g. `mem0_memory`), and paste the full contents of
   [`openwebui-filter/openwebui_mem0_filter.py`](openwebui-filter/openwebui_mem0_filter.py)
   into the code editor.
4. **Save**. Flip the function's toggle to **Active** on the Functions list page.
5. Click the function's **valves/settings (gear)** icon and set:
   - `mem0_url`: `http://mem0:8000` (same network) or `http://<docker-host>:8000` (LAN)
   - `mem0_api_key`: the value of `MEM0_API_KEY` from `secrets.env`
   - `user_id_field`: `email` (recommended — the account email matches the `user_id` MCP clients pass, so both share one memory space)
   - leave the rest at defaults (`top_k 8`, `threshold 0.35`, `search_timeout 60`, `learn on`)
6. In the Functions list, enable **Global** on the function so every model/chat uses it (or leave it off and enable per-user via User Valves).

**7c. Verify the OWUI wiring**

1. Start a chat with any model, say something memorable ("my favorite robot is R2-D2").
2. Within ~30 s you should see a `recalled/stored` status hint (if `show_status` is on) — the outlet learned the fact.
3. From the mem0 REST API directly:

   ```bash
   curl -s "http://127.0.0.1:8000/memories?user_id=<account-email>" \
     -H "Authorization: Bearer $(grep ^MEM0_API_KEY secrets.env | cut -d= -f2)"
   ```

4. From Crush (step 6 installed): `search my memory for: favorite robot` — the same fact comes back.

**Why user_id_field=email matters**: memories are keyed per `user_id`. Choose **one canonical id per person** (the Open WebUI account email is a good one) and use it consistently in MCP calls and the OWUI filter, or you'll end up with parallel memory spaces for the same person.

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