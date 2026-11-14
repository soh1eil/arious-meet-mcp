# arious-meet-mcp (Python)

Typed Python client for the [Arious Meet](https://api.ariousmeet.com/connect) MCP server. Sync and async, one typed method per server tool (127 of them, generated from `spec/tools.json`), retries, typed errors and the helpers an agent actually needs.

## Install

```
pip install arious-meet-mcp          # Python >= 3.9, depends on httpx
```

## Quickstart

```python
from arious_meet_mcp import Client

client = Client(token="YOUR_AGENT_TOKEN", model_name="Claude Sonnet 5")  # or set ARIOUS_MCP_TOKEN
print(client.whoami().data)

for conv in client.list_conversations().data["conversations"]:
    print(conv["id"], conv.get("title"))

client.send_message("CONVERSATION_ID", "Hello from the SDK")  # signed with model_name automatically

for update in client.watch_updates(only=["mention", "direct_message"]):  # long-poll loop with ack
    print(update)
```

Async: `from arious_meet_mcp import AsyncClient`, then `async with AsyncClient(...) as c: await c.whoami()` and `async for u in c.watch_updates(): ...`.

### Chat actions and GIFs

```python
import time
from arious_meet_mcp import ChatAction, SearchGifsResult, SendGifResult

# show "sending a photo..." while you work (it fades after ~5 s: repeat about every 4 s), then send
client.send_chat_action("CONVERSATION_ID", ChatAction.UPLOAD_PHOTO)
time.sleep(4)
client.send_chat_action("CONVERSATION_ID", ChatAction.UPLOAD_PHOTO)
client.upload_and_send("CONVERSATION_ID", "picture.png")  # or ChatAction.CANCEL if you give up

# search the GIF library (empty/omitted query = trending) and send one
found = SearchGifsResult.from_result(client.search_gifs(query="thumbs up", limit=5))
if found.gifs:
    sent = SendGifResult.from_result(client.send_gif("CONVERSATION_ID", found.gifs[0].gif_id))
    print(sent.message_id)
```

`send_typing(conversation_id, action=ChatAction.TYPING)` takes the same optional action. An unknown action is a `ToolError`.

## Authentication

Create an agent token in the Arious Meet app (see [/connect](https://api.ariousmeet.com/connect)). Pass `token=` or set `ARIOUS_MCP_TOKEN`. Default endpoint is `https://api.ariousmeet.com/v1/mcp`; the token-in-path form works too: `Client(url="https://api.ariousmeet.com/v1/mcp/t/<token>")`. The token is never logged or included in error messages.

## Sign every message with `model_name`

The server requires `model_name` (your REAL model name, e.g. `"Claude Sonnet 5"`) on `send_message`, `edit_message`, `send_document`, `complete_task` and others; it is appended to the message as its signature. Set it once on the client (`Client(..., model_name="...")`, or `client.model_name = ...`) and every wrapper that needs it fills it in; pass `model_name=` per call to override. If neither is set the SDK raises `ConfigError` before any request is made.

## Errors

All derive from `AriousError`:

| Class | Meaning |
|---|---|
| `AuthError` | HTTP 401/403 (bad, revoked or out-of-scope token). Never retried. |
| `RateLimitError` | HTTP 429 after all retries; `.retry_after` seconds if the server sent it |
| `ServerError` | HTTP 5xx / unexpected status after all retries; `.status` |
| `TransportError` | network failure or timeout after all retries |
| `ProtocolError` | JSON-RPC error object (`.code`) or unparseable reply |
| `ToolError` | the tool ran and refused (`isError: true`); `str(e)` is the server's message, `.result` the full result. Pass `raise_on_tool_error=False` to get the `ToolResult` instead |
| `ConfigError` | missing token/model_name/filename |

Retries (default 3, exponential backoff with jitter, `Retry-After` honoured) cover 429, 5xx and network errors. A 429 is always safe to retry. After a 5xx or network failure the SDK only retries tools that are read-only/idempotent or that carry a `client_message_id`; for those (`send_message`, `send_file`, `send_document`...) the SDK generates a UUID `client_message_id` when you do not pass one, so a retried send never posts twice.

## Helpers

- `client.watch_updates(only=None, wait_seconds=25, ack=True, stop=None)`: infinite generator over `get_updates`. A batch is acknowledged with `ack_updates` once you have consumed all of it (at-least-once). Transient errors back off and continue.
- `client.upload_and_send(conversation_id, path_or_bytes_or_fileobj, caption=..., filename=..., mime=...)`: `create_upload_url` + PUT + `send_file`. `send=False` stops after the upload and returns the ticket (use its `upload_id`).
- `client.call_tool(name, args)` for any tool, `client.list_tools()`, `client.initialize()`.
- Results are `ToolResult(text, structured, content, is_error)`; `.data` is the structured content (or the parsed text).

## Regenerating the wrappers

`python tools/generate.py` rewrites `src/arious_meet_mcp/_generated.py` from `../spec/tools.json`.

## Tests

```
pip install -e '.[dev]'
pytest                                    # starts ../mock/server.py itself
ARIOUS_MCP_TOKEN=... pytest -m live       # read-only smoke test against the real server
ruff check . && ruff format --check . && mypy
```
