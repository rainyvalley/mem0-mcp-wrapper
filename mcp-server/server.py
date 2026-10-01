"""mem0-mcp — MCP server wrapping a self-hosted mem0 REST API.

Exposes the same memory layer Open WebUI uses (Qdrant + mem0, keyed by user
email) to any MCP client on the LAN — Crush on any machine, OWUI, anything
that speaks MCP. It is a thin HTTP wrapper: no local vector store, no LLM
calls of its own; all memory stays in the single mem0/Qdrant instance.

Transport: streamable HTTP at /mcp (port 8300). Auth: Bearer $MEM0_API_KEY on
every request — the same key the mem0 REST API itself requires. The MCP layer
adds its own bearer-token check (MCP_BEARER_TOKEN, LAN secret) so anything on
the LAN can't invoke memory tools without the token.
"""

import json
import os
import secrets

import httpx
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver import MCPServer

MEM0_URL = os.environ.get("MEM0_URL", "http://mem0:8000").rstrip("/")
MEM0_API_KEY = os.environ.get("MEM0_API_KEY", "")
DEFAULT_USER = os.environ.get("MEM0_DEFAULT_USER", "")
# LAN auth: the MCP endpoint is LAN-reachable, so require a bearer token on
# every request (token_verifier below). Stable value: set MCP_BEARER_TOKEN in
# env (e.g. mcp.env via env_file); unset -> random per boot, logged once at startup
# (ephemeral fallback: every restart rotates it, so prefer the env file).
MCP_BEARER_TOKEN = os.environ.get("MCP_BEARER_TOKEN") or secrets.token_urlsafe(24)


class StaticTokenVerifier:
    """TokenVerifier accepting exactly one static bearer token (our LAN secret)."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if secrets.compare_digest(token, MCP_BEARER_TOKEN):
            return AccessToken(token=token, client_id="mcp-client", scopes=[],
                                expires_at=None, resource=None)
        return None


def _auth_settings() -> "AuthSettings | None":
    """Resource-server-only auth: bearer required, no OAuth dance.

    mcp 2.x demands AuthSettings whenever a token_verifier is set. We run as a
    pure RS on a LAN: resource_server_url is this server's own URL and
    validate_token_resource is False because our static token has no RFC 8707
    resource indicator — the verifier itself is the whole check.
    """
    try:
        from mcp.server.auth.settings import AuthSettings
        base = os.environ.get("MCP_PUBLIC_URL", "http://localhost:8300")
        return AuthSettings(issuer_url=base, resource_server_url=base,
                            validate_token_resource=False)
    except Exception:
        return None


mcp = MCPServer(name="mem0", token_verifier=StaticTokenVerifier(),
                auth=_auth_settings(), instructions=(
    "Tools for the shared long-term memory layer (mem0/Qdrant). Memories are "
    f"keyed by user email; the primary user is {DEFAULT_USER}. Prefer search_memory "
    "before answering questions about the user; call add_memory when you learn "
    "a durable fact, preference, or instruction worth remembering across sessions."
))


def _client() -> httpx.Client:
    headers = {"Authorization": f"Bearer {MEM0_API_KEY}"} if MEM0_API_KEY else {}
    return httpx.Client(base_url=MEM0_URL, headers=headers, timeout=httpx.Timeout(200.0, connect=10.0))


def _tool_err(action: str, e: Exception) -> str:
    detail = ""
    if isinstance(e, httpx.HTTPStatusError):
        detail = f" (HTTP {e.response.status_code})"
    return f"mem0 {action} failed{detail}: {e}"


@mcp.tool()
def search_memory(query: str, user_id: str = DEFAULT_USER, top_k: int = 8, threshold: float = 0.35) -> str:
    """Search long-term memories. Returns memories relevant to the query for the given user.

    Args:
        query: What to look for, e.g. "favorite color" or the user's current question.
        user_id: Memory space owner (user email). Defaults to the primary user.
        top_k: Maximum number of memories to return.
        threshold: Minimum similarity score (0-1) for a memory to be returned.
    """
    try:
        with _client() as c:
            r = c.post("/search", json={"query": query[:2000], "user_id": user_id,
                                        "top_k": top_k, "threshold": threshold})
            r.raise_for_status()
            results = r.json().get("results", [])
    except Exception as e:
        return _tool_err("search", e)
    if not results:
        return f"No memories found for {user_id!r} matching {query!r}."
    lines = [f"{m.get('memory', '')}  (score {round(m.get('score', 0), 3)})" for m in results]
    return "\n".join(lines)


@mcp.tool()
def add_memory(messages: str, user_id: str = DEFAULT_USER, infer: bool = True) -> str:
    """Store new long-term memories from a conversation exchange.

    Args:
        messages: JSON array of {"role": "user"|"assistant", "content": "..."} messages.
            Typically the exchange worth remembering, e.g. a user preference or fact.
        user_id: Memory space owner (user email). Defaults to the primary user.
        infer: When true, an LLM extracts the durable facts from the messages
            (recommended). When false, the raw message text is stored as-is.
    """
    try:
        msgs = json.loads(messages)
    except json.JSONDecodeError as e:
        return f"messages must be a JSON array of role/content objects: {e}"
    if not isinstance(msgs, list) or not msgs:
        return "messages must be a non-empty JSON array of role/content objects."
    try:
        with _client() as c:
            r = c.post("/memories", json={"messages": msgs, "user_id": user_id, "infer": infer})
            r.raise_for_status()
            results = r.json().get("results", [])
    except Exception as e:
        return _tool_err("add", e)
    if not results:
        return "No new memories extracted (nothing durable in the exchange, or all facts already known)."
    events = []
    for m in results:
        tag = m.get("event", "ADD")
        events.append(f"[{tag}] {m.get('memory', '')}")
    return "Stored memories:\n" + "\n".join(events)


@mcp.tool()
def list_memories(user_id: str = DEFAULT_USER, limit: int = 1000) -> str:
    """List all stored long-term memories for a user, newest first.

    Args:
        user_id: Memory space owner (user email). Defaults to the primary user.
        limit: Maximum number of memories to return.
    """
    try:
        with _client() as c:
            r = c.get("/memories", params={"user_id": user_id, "limit": limit})
            r.raise_for_status()
            results = r.json().get("results", [])
    except Exception as e:
        return _tool_err("list", e)
    if not results:
        return f"No memories stored for {user_id!r} yet."
    return "\n".join(f"- {m.get('memory', '')}" for m in results)


@mcp.tool()
def get_memory(memory_id: str) -> str:
    """Fetch one long-term memory by its ID, including metadata and timestamps.

    Args:
        memory_id: UUID of the memory (get IDs from search_memory or list_memories).
    """
    try:
        with _client() as c:
            r = c.get(f"/memories/{memory_id}")
            r.raise_for_status()
            m = r.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Memory {memory_id} not found."
        return _tool_err("get", e)
    except Exception as e:
        return _tool_err("get", e)
    return json.dumps(m, ensure_ascii=False, indent=1)


@mcp.tool()
def update_memory(memory_id: str, text: str = "", metadata_json: str = "") -> str:
    """Edit an existing memory's text and/or metadata (no LLM re-inference).

    Args:
        memory_id: UUID of the memory to edit.
        text: Replacement text for the memory (empty string = leave text unchanged).
        metadata_json: JSON object to merge into the memory's metadata
            (empty string = leave metadata unchanged).
    """
    if not text and not metadata_json:
        return "Nothing to update: pass text and/or metadata_json."
    body = {}
    if text:
        body["text"] = text
    if metadata_json:
        try:
            body["metadata"] = json.loads(metadata_json)
        except json.JSONDecodeError as e:
            return f"metadata_json must be a JSON object: {e}"
    try:
        with _client() as c:
            r = c.put(f"/memories/{memory_id}", json=body)
            r.raise_for_status()
            return "Memory updated: " + json.dumps(r.json(), ensure_ascii=False, indent=1)
    except Exception as e:
        return _tool_err("update", e)


@mcp.tool()
def memory_history(memory_id: str) -> str:
    """Show the audit trail of a memory (ADD/UPDATE/DELETE events with before/after text).

    Args:
        memory_id: UUID of the memory to inspect.
    """
    try:
        with _client() as c:
            r = c.get(f"/memories/{memory_id}/history")
            r.raise_for_status()
            events = r.json()
    except Exception as e:
        return _tool_err("history", e)
    if not events:
        return "No history events recorded for this memory."
    lines = []
    for e in events:
        old = (e.get("old_memory") or "")[:60]
        new = (e.get("new_memory") or "")[:60]
        lines.append(f"[{e.get('event', '?')}] {e.get('created_at', '')[:19]}  "
                     f"old={old!r} -> new={new!r}")
    return "\n".join(lines)


@mcp.tool()
def delete_memory(memory_id: str) -> str:
    """Delete a single long-term memory by its ID (get IDs from search_memory or list_memories).

    Args:
        memory_id: UUID of the memory to delete.
    """
    try:
        with _client() as c:
            r = c.delete(f"/memories/{memory_id}")
            r.raise_for_status()
    except Exception as e:
        return _tool_err("delete", e)
    return f"Deleted memory {memory_id}."


@mcp.tool()
def delete_all_memories(user_id: str) -> str:
    """Wipe ALL long-term memories for a user. Destructive; requires an explicit user_id.

    Args:
        user_id: Memory space owner (user email) whose memories will be wiped.
    """
    if user_id == DEFAULT_USER and not os.environ.get("MEM0_ALLOW_WIPE_DEFAULT", ""):
        return (f"Refusing to wipe the default user ({user_id}) without MEM0_ALLOW_WIPE_DEFAULT set "
                "in the mem0-mcp container — wipe test/secondary users by their own id.")
    try:
        with _client() as c:
            r = c.delete("/memories", params={"user_id": user_id})
            r.raise_for_status()
    except Exception as e:
        return _tool_err("wipe", e)
    return f"Wiped all memories for {user_id}."


@mcp.tool()
def mem0_health() -> str:
    """Check the mem0 memory backend status (LLM + embedder models in use)."""
    try:
        with _client() as c:
            r = c.get("/health")
            r.raise_for_status()
            return json.dumps(r.json())
    except Exception as e:
        return _tool_err("health", e)


if __name__ == "__main__":
    print(f"mem0-mcp listening on :8300 (MCP bearer token: {MCP_BEARER_TOKEN})", flush=True)
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.environ.get("MCP_PORT", "8300")))