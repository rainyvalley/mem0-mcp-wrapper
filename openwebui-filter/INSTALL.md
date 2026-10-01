# Adding the memory filter to Open WebUI

The filter in this folder (`openwebui_mem0_filter.py`) makes every Open WebUI
chat participate in the shared memory layer:

- **inlet** (before the model runs): searches the user's memory space and
  injects the most relevant memories as a system block
- **outlet** (after the exchange): fires a background task that stores durable
  facts from the last exchange (fire-and-forget, never blocks the chat)

## Install

1. Copy the whole file contents.
2. Open WebUI → **Admin Panel → Functions → +** (new Function).
3. Paste, Save, then toggle it **Active**. To apply to everyone, also enable
   **Global** (the toggle row in the functions list).
4. Set the valves (function detail → Valves / gear icon):
   - `mem0_url`: `http://mem0:8000` — the compose service name, or
     `http://<docker-host>:8000` from outside the network
   - `mem0_api_key`: the `MEM0_API_KEY` from `secrets.env`
   - `user_id_field`: `email` (recommended — matches what MCP clients use)

Memories are keyed by the Open WebUI account email, so the OWUI user and the
`user_id` MCP clients pass refer to the same memory space.