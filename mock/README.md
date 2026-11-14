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
`initialize` (returns `Mcp-Session-Id` header, echoes known protocolVersion), `notifications/initialized` (202), `ping`, `tools/list` (the full 124-tool catalogue from `spec/tools.json`), `tools/call`, `resources/list|subscribe|unsubscribe`, `GET /v1/mcp` with `Accept: text/event-stream` (emits `notifications/resources/updated` with `_meta["arious/inbox"]` for pushed items, closes after `?hold=` seconds, default 0.3).

## Implemented tools (others return an `isError` result "not implemented by the mock")
`whoami`, `get_handbook`, `search_app_guide`, `list_organizations`, `send_message` (requires `model_name`; honours `client_message_id` and returns `deduplicated:true` on a repeat), `get_updates` (`cursor`, `ack`, `only`, `wait_seconds` capped at 3s; result `{updates:[...], next_cursor}`), `ack_updates`, `create_upload_url` (returns `upload_url` on this mock, `PUT /v1/agent-uploads/<id>`), `send_file`, plus test tools `mock_tool_error` (isError result) and `mock_protocol_error` (JSON-RPC error -32602). Unknown tool names give JSON-RPC error -32602.

## Control endpoints
`POST /__mock/push {"token":"test-x","items":[{"kind":"mention","conversation_id":"c1","text":"hi"}]}` queues updates; `POST /__mock/reset`; `GET /__mock/log` returns every JSON-RPC request seen and every message sent.
