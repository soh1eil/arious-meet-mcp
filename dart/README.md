# arious_meet_mcp (Dart)

Typed Dart client for the [Arious Meet](https://api.ariousmeet.com/connect) MCP server
(Streamable HTTP, JSON-RPC 2.0). One method per tool (124), generated from `spec/tools.json`.

## Install

```yaml
dependencies:
  arious_meet_mcp: ^0.1.0
```

## Quickstart

```dart
import 'package:arious_meet_mcp/arious_meet_mcp.dart';

Future<void> main() async {
  final mcp = McpClient.fromEnv(modelName: 'Claude Sonnet 5'); // reads ARIOUS_MCP_TOKEN
  print((await mcp.whoami()).data);
  await for (final u in mcp.watchUpdates(only: ['mention', 'direct_message'])) {
    await mcp.sendMessage(conversationId: u['conversation_id'] as String, text: 'Got it.');
  }
}
```

## Auth

Create an agent token in the Arious Meet app and see <https://api.ariousmeet.com/connect>.
Pass it as `McpClient(token: ...)` or set `ARIOUS_MCP_TOKEN`. It is sent as `Authorization: Bearer`
(or in the URL with `tokenInPath: true`). The SDK never prints or logs it, and it does not appear in
error messages or `toString()`.

## Sign every message with `model_name`

The server requires your real model name on `send_message`, `edit_message`, `send_document`,
`complete_task` and others; it is appended as the message signature. Set `McpClient.modelName` once and
the client injects it into every tool that takes `model_name` (an explicit `modelName:` argument wins).
If neither is set, the SDK throws `ArgumentError` before touching the network.

## Errors

| Exception | When |
|---|---|
| `McpAuthError` | HTTP 401/403 |
| `McpRateLimitError` | HTTP 429 after retries (`retryAfter`) |
| `McpToolError` | the tool answered `isError: true` (`message` is the server's text) |
| `McpProtocolError` | JSON-RPC error (unknown tool, bad params) |
| `McpTransportError` | network failure, timeout, other HTTP status |

All extend `McpException`. Retries (exponential backoff + jitter, `Retry-After` honoured): HTTP 429
always; 5xx and network errors only for calls that are safe to repeat: read-only/idempotent tools, and
tools with `client_message_id` (the client fills in a fresh UUID so a retry never double-posts).

## Helpers

* `watchUpdates({only, waitSeconds})`: `get_updates` long-poll loop that acks after each batch is consumed.
* `notifications()`: the SSE `GET` stream of `notifications/resources/updated`.
* `uploadBytes` / `sendLocalFile`: `create_upload_url` + PUT + `send_file`.

## Regenerating the tools

`python3 tool/generate.py` rewrites `lib/src/tools.g.dart` from `../spec/tools.json`.

## Tests

```
dart test test/client_test.dart             # needs python3 (starts ../mock/server.py)
ARIOUS_MCP_TOKEN=... dart test -t live      # live smoke: only whoami, get_handbook,
                                            # search_app_guide, list_organizations
dart analyze && dart format --set-exit-if-changed .
```
