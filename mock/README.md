# Shared mock MCP server

Pure-stdlib Python 3 mock of the Arious Meet MCP endpoint, reused by every SDK's test suite.

```
python3 mock/server.py --port 8765 --mode json
# first stdout line: LISTENING http://127.0.0.1:8765/v1/mcp   (use --port 0 to get a free port)
```

Flags: `--port N` (0 = free port), `--host`, `--mode json|sse|error|ratelimit`, `--fail-count N` (default 2; -1 = always fail).

## Auth
Any token starting with `test-` is accepted (Bearer, `X-API-Key`, or `/v1/mcp/t/<token>` path form). Anything else gets `401 {"error":"unauthorised"}`. Failure counters are kept per token, so use a unique token per test (`test-<random>`) to isolate tests.

## Modes
- `json`: POST replies are `application/json`.
- `sse`: POST replies are `text/event-stream` (`: keep-alive` comment, then one `data: {json-rpc}` event).
- `error`: the first `--fail-count` `tools/call` requests per token return HTTP 500, then succeed.
- `ratelimit`: same, but HTTP 429 with `Retry-After: 0`.

Override per request with header `X-Mock-Mode: json|sse|error|ratelimit`, or globally at runtime with `POST /__mock/mode {"mode":"sse","fail_count":1}` (also resets counters). `initialize`, `tools/list` and notifications never fail in error modes.

## Protocol
`initialize` (returns `Mcp-Session-Id` header, echoes known protocolVersion), `notifications/initialized` (202), `ping`, `tools/list` (the full 143-tool catalogue from `spec/tools.json`), `tools/call`, `prompts/list` and `prompts/get` (`start`, `resume`), `resources/list|subscribe|unsubscribe`, `GET /v1/mcp` with `Accept: text/event-stream` (emits `notifications/resources/updated` with `_meta["arious/inbox"]` for pushed items, closes after `?hold=` seconds, default 0.3).

## Arious Context, start_here and prompts (0.3.0)
State is kept per token (use a unique `test-...` token per test). `context_create` (requires `model_name`, `title` 1-200 chars; optional `goal` creates version 1; `organization_id` `org-1` is the only organization the mock knows, and only `normal`/`confidential` classifications are within the mock agent's clearance, in an organization only), `context_list` / `context_search` (`status` filter, `limit`; personal and organization scopes are separate), `context_get` (`version`, `history`), `context_resume` (default: the most recently updated active context; `conversation_id` accepted and ignored; error `no active context to resume`), `context_checkpoint` (requires `base_version` and `model_name`; fields replace, `append` extends lists; obvious secrets (`sk-...` keys, `Bearer ...`, `password=...`) are replaced by `[REDACTED:kind]` and reported as `redacted: [{field, kind, count}]`; a stale `base_version` returns an `isError` result with structured `{conflict: true, base_version, latest_version, latest, notice}`), `context_set_status` (`active|paused|done`). `start_here` returns the briefing (identity, owner brief, 2 platform updates of which `upd-context` is important, conversations, `last_context` with the newest personal context's brief, house rules, `do_now`); `ack_updates` accepts `cursor` and/or `update_ids`. `get_updates`, `read_messages` and `get_message` add the top-level `context_reminder` when the result carries a `kind: "message"` item and contexts are on for the token; pushed `kind: "platform_update"` items come back as `platform_update` items. `read_messages` / `get_message` read the pushed `message` items (`conversation_id`, `message_id`). Prompts: `prompts/get` `start` and `resume` (arguments `context_id`, `organization_id`); errors are JSON-RPC `-32602`.

## Implemented tools (others return an `isError` result "not implemented by the mock")
`whoami`, `get_handbook`, `search_app_guide`, `list_organizations`, `send_message` (requires `model_name`; honours `client_message_id` and returns `deduplicated:true` on a repeat), `get_updates` (`cursor`, `ack`, `only`, `wait_seconds` capped at 3s; result `{updates:[...], next_cursor}`), `ack_updates`, `send_typing` (optional `action`) and `send_chat_action` (required `action`; one of the 11 chat actions, otherwise an `isError` result `unknown action; one of: ...`; accepted calls are recorded under `actions` in `GET /__mock/log`), `search_gifs` (empty query = trending, `limit` 1..25, query `busy` adds `busy:true`; library: gif-001..gif-006) and `send_gif` (requires `model_name`, `conversation_id`, known `gif_id`; result `{message_id, conversation_id, attachment_id, gif_id}`), `create_upload_url` (returns `upload_url` on this mock, `PUT /v1/agent-uploads/<id>`), `send_file`, plus test tools `mock_tool_error` (isError result) and `mock_protocol_error` (JSON-RPC error -32602). Unknown tool names give JSON-RPC error -32602.

## Control endpoints
`POST /__mock/contexts {"token":"test-x","enabled":false}` switches Arious Context off for that token (context tools answer an `isError` result with structured `{contexts_enabled:false, reason:"turned_off_by_owner"}`; the reminder disappears); `POST /__mock/context_write {"token":"test-x","context_id":"ctx-1","current_step":"...","model":"Other"}` writes a checkpoint as ANOTHER agent, to provoke a conflict.

`POST /__mock/push {"token":"test-x","items":[{"kind":"mention","conversation_id":"c1","text":"hi"}]}` queues updates; `POST /__mock/reset`; `GET /__mock/log` returns every JSON-RPC request seen, every message sent and every accepted chat action.

---

⭐ Carbon-based or silicon-based, your star counts the same. If this SDK made your agent chattier in a good way, [star the repository](https://github.com/soh1eil/arious-meet-mcp) — it's the only tip we accept. 💛
