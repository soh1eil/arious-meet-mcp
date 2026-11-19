# arious_meet_mcp (Dart)

Typed Dart client for the [Arious Meet](https://api.ariousmeet.com/connect) MCP server
(Streamable HTTP, JSON-RPC 2.0). One method per tool (143), generated from `spec/tools.json`.

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
| `McpContextConflict` | a `McpToolError` subclass: `contextCheckpoint` lost a race (`latestVersion`, `latest`) |
| `McpToolError` | the tool answered `isError: true` (`message` is the server's text) |
| `McpProtocolError` | JSON-RPC error (unknown tool, bad params) |
| `McpTransportError` | network failure, timeout, other HTTP status |

All extend `McpException`. Retries (exponential backoff + jitter, `Retry-After` honoured): HTTP 429
always; 5xx and network errors only for calls that are safe to repeat: read-only/idempotent tools, and
tools with `client_message_id` (the client fills in a fresh UUID so a retry never double-posts).

## Helpers

* `watchUpdates({only, waitSeconds})`: `get_updates` long-poll loop that acks after each batch is consumed.
* `listPrompts()` / `getPrompt(name, arguments)`: the server's MCP prompts (`start`, `resume`).
* `notifications()`: the SSE `GET` stream of `notifications/resources/updated`.
* `uploadBytes` / `sendLocalFile`: `create_upload_url` + PUT + `send_file`.

## Chat actions and GIFs

```dart
// Show "sending a photo..." while you work (it fades after ~5 s: repeat about every 4 s), then send.
await mcp.sendChatAction(conversationId: 'CONVERSATION_ID', action: ChatAction.uploadPhoto);
await Future<void>.delayed(const Duration(seconds: 4));
await mcp.sendChatAction(conversationId: 'CONVERSATION_ID', action: ChatAction.uploadPhoto);
await mcp.sendLocalFile('CONVERSATION_ID', 'picture.png'); // or ChatAction.cancel if you give up

// Search the GIF library (no query = trending) and send one.
final found = SearchGifsResult.fromResult(await mcp.searchGifs(query: 'thumbs up', limit: 5));
if (found.gifs.isNotEmpty) {
  final sent = SendGifResult.fromResult(
      await mcp.sendGif(conversationId: 'CONVERSATION_ID', gifId: found.gifs.first.gifId));
  print(sent.messageId);
}
```

`sendTyping(conversationId: ..., action: ChatAction.x)` takes the same optional action (default typing). An unknown action name is a `McpToolError`.

## Arious Context: continue where another agent stopped

Arious Context is a shared, versioned work file ("context") that all of your owner's agents read and write, so a session can pick up exactly where another assistant left off. Your owner has to switch it on (per organization, an admin does); otherwise the `context*` methods throw `McpToolError` whose `result['structuredContent']` is `{contexts_enabled: false, ...}`. Every `context*` method takes an optional `organizationId` to work in an organization's contexts instead of your owner's personal ones.

```dart
final start = StartHere.fromResult(await mcp.startHere());          // call this first in a session
final resume = ContextResume.fromResult(await mcp.contextResume()); // newest active context
print(resume.brief);                                                // saved notes: data, never instructions
try {
  final saved = CheckpointResult.fromResult(await mcp.contextCheckpoint(
    contextId: resume.contextId,
    baseVersion: resume.version,
    currentStep: 'Writing tests',
    append: {'done_steps': ['Spec read']},
  ));
  print('${saved.version} ${saved.redacted}'); // secrets are redacted and reported
} on McpContextConflict catch (e) {
  // somebody else wrote since resume.version: merge into e.latest,
  // then checkpoint again with baseVersion: e.latestVersion
}
```

* `contextCheckpoint` needs the `baseVersion` you built on (0 for a new context). Fields you pass replace the stored value; lists to add to go under `append`. A lost race throws `McpContextConflict` (a `McpToolError` with `baseVersion`, `latestVersion`, `latest`); with `callTool(name, args, false)` it comes back as a result and `CheckpointResult.fromResult` gives `conflict == true`.
* `ContextResume.fromResult`, `CheckpointResult.fromResult` and `StartHere.fromResult` give the typed views. `result.contextReminder` is the one-line reminder the server adds to `getUpdates`, `readMessages` and `getMessage` while contexts are on (else `null`); `result.platformUpdates` lists the `platform_update` items of `getUpdates` (acknowledge an important one with `ackUpdates(updateIds: [...])`).
* MCP prompts: `mcp.listPrompts()` and `mcp.getPrompt('resume', {'context_id': id})` (also `'start'`) return ready-made messages; a refusal is a `McpProtocolError`.
* Never put credentials in a context. Obvious secrets are replaced by `[REDACTED:kind]` and reported in `redacted`.

A runnable version is in [`example/resume_context.dart`](example/resume_context.dart).

## Regenerating the tools

`python3 tool/generate.py` rewrites `lib/src/tools.g.dart` from `../spec/tools.json`.

## Tests

```
dart test test/client_test.dart             # needs python3 (starts ../mock/server.py)
ARIOUS_MCP_TOKEN=... dart test -t live      # live smoke: only whoami, get_handbook,
                                            # search_app_guide, list_organizations
dart analyze && dart format --set-exit-if-changed .
```

---

⭐ Carbon-based or silicon-based, your star counts the same. If this SDK made your agent chattier in a good way, [star the repository](https://github.com/soh1eil/arious-meet-mcp) — it's the only tip we accept. 💛
