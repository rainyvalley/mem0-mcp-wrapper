# Example MCP client configs. Values here assume the compose quickstart.

# ---- Crush (https://github.com/charmbracelet/crush) --------------------
# In ~/.config/crush/crushrc (Bash):
#
#   MEM0_MCP_TOKEN="..."   # the MCP_BEARER_TOKEN from secrets.env
#   mcp add mem0 --type http \
#     --url "http://<docker-host>:8300/mcp" \
#     --header Authorization "Bearer $MEM0_MCP_TOKEN"
#
# In crush.json (JSON, header values are shell-expanded at load):
#   "mcp": {
#     "mem0": {
#       "type": "http",
#       "url": "http://<docker-host>:8300/mcp",
#       "headers": { "Authorization": "Bearer $MEM0_MCP_TOKEN" }
#     }
#   }

# ---- Generic streamable-HTTP MCP client --------------------------------
#   url:     http://<docker-host>:8300/mcp
#   method:  POST (JSON-RPC 2.0 over streamable HTTP)
#   headers: Authorization: Bearer <MEM0_MCP_TOKEN>
#            Accept: application/json, text/event-stream
#
# Handshake order matters:
#   1. initialize            (request, id=1)   -> read Mcp-Session-Id header
#   2. notifications/initialized  (NOTIFICATION - no id!) with the session id
#   3. tools/call ...        (request, id=2)   with the session id
# A request before the `initialized` notification is rejected INVALID_PARAMS.

# ---- Smoke test from the CLI -------------------------------------------
#   curl -s -X POST http://<docker-host>:8300/mcp \
#     -H "Authorization: Bearer $MEM0_MCP_TOKEN" \
#     -H "Content-Type: application/json" \
#     -H "Accept: application/json, text/event-stream" \
#     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}'