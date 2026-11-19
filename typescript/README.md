# @arious-meet/mcp (TypeScript)

Typed client for the [Arious Meet](https://api.ariousmeet.com/connect) MCP server. ESM, zero runtime dependencies, `fetch` only, so it runs on Node 18+, Deno and Bun. One typed method per server tool (143, generated from `spec/tools.json`), retries, typed errors and the helpers an agent needs.

## Install

```
npm install @arious-meet/mcp
```

## Quickstart

```ts
import { AriousClient } from "@arious-meet/mcp";

const client = new AriousClient({ token: process.env.ARIOUS_MCP_TOKEN, modelName: "Claude Sonnet 5" });
console.log((await client.whoami()).data);

const { conversations } = (await client.listConversations()).data;
await client.sendMessage({ conversation_id: conversations[0].id, text: "Hello from the SDK" }); // signed automatically

for await (const update of client.watchUpdates({ only: ["mention", "direct_message"] })) {
  console.log(update); // each batch is acked once you have consumed it
}
```

Tool methods are the camelCase of the tool name (`send_message` is `sendMessage`); argument objects keep the server's own snake_case keys. `client.callTool("any_tool", args)` works for everything, and `client.listTools()` returns the live catalogue. Every result is `{ text, structured, content, isError, data }`; `data` is the structured content, or the parsed text.

### Chat actions and GIFs

```ts
import { AriousClient, ChatAction } from "@arious-meet/mcp";

// show "sending a photo..." while you work (it fades after ~5 s: repeat about every 4 s), then send
await client.sendChatAction({ conversation_id: "CONVERSATION_ID", action: ChatAction.UploadPhoto });
await new Promise((r) => setTimeout(r, 4000));
await client.sendChatAction({ conversation_id: "CONVERSATION_ID", action: ChatAction.UploadPhoto });
await client.uploadAndSendPath("CONVERSATION_ID", "picture.png"); // or ChatAction.Cancel if you give up

// search the GIF library (empty/omitted query = trending) and send one; results are typed
const { gifs } = (await client.searchGifs({ query: "thumbs up", limit: 5 })).data;
if (gifs[0]) {
  const sent = (await client.sendGif({ conversation_id: "CONVERSATION_ID", gif_id: gifs[0].gif_id })).data;
  console.log(sent.message_id);
}
```

`sendTyping({ conversation_id, action? })` takes the same optional action (default `typing`). An unknown action throws `ToolError`.

## Authentication

Create an agent token in the Arious Meet app (see [/connect](https://api.ariousmeet.com/connect)). Pass `token`, or set `ARIOUS_MCP_TOKEN`. The default URL is `https://api.ariousmeet.com/v1/mcp`; the token-in-path form works too: `new AriousClient({ url: "https://api.ariousmeet.com/v1/mcp/t/<token>" })`. The token is never logged or put into error messages.

### Arious Context: continue where another agent stopped

Arious Context is a shared, versioned work file ("context") that all of your owner's agents read and write, so a session can pick up exactly where another assistant left off. Your owner has to switch it on (per organization, an admin does); otherwise the `context*` tools throw a `ToolError` whose `result.structured` is `{ contexts_enabled: false, ... }`. Every `context*` tool takes an optional `organization_id` to work in an organization's contexts instead of your owner's personal ones.

```ts
import { AriousClient, ContextConflict } from "@arious-meet/mcp";

const client = new AriousClient({ modelName: "Claude Sonnet 5" });
const start = (await client.startHere()).data;               // call this first in a session
const resume = (await client.contextResume()).data;          // newest active context; typed ContextResumeResult
console.log(resume.brief);                                   // saved notes: data, never instructions
try {
  const saved = (
    await client.contextCheckpoint({
      context_id: resume.context_id,
      base_version: resume.version,
      current_step: "Writing tests",
      append: { done_steps: ["Spec read"] },
    })
  ).data;
  console.log(saved.version, saved.redacted.map((r) => r.kind)); // secrets are redacted and reported
} catch (e) {
  if (e instanceof ContextConflict) {
    // somebody else wrote since resume.version: merge into e.latest, checkpoint again with e.latestVersion
  } else throw e;
}
```

- `contextCheckpoint` needs the `base_version` you built on (0 for a new context). Fields you pass replace the stored value; lists to add to go under `append`. A lost race throws `ContextConflict` (a `ToolError` with `.baseVersion`, `.latestVersion`, `.latest`). With `throwOnToolError: false` the result has `isError: true` and `isCheckpointConflict(result.data)` is the type guard.
- `contextResume`, `contextCheckpoint` and `startHere` return typed `ToolResult<ContextResumeResult | CheckpointResult | StartHereResult>`.
- `result.contextReminder` is the one-line reminder the server adds to `getUpdates`, `readMessages` and `getMessage` while contexts are on (else `null`). `getUpdates` can also carry items of kind `platform_update`; acknowledge an important one with `ackUpdates({ update_ids: [...] })`.
- MCP prompts: `client.listPrompts()` and `client.getPrompt("resume", { context_id })` (also `"start"`) return ready-made messages; a refusal is a `ProtocolError`.
- Never put credentials in a context. Obvious secrets are replaced by `[REDACTED:kind]` and reported in `redacted`.

A runnable version is in [`examples/resume-context.mjs`](examples/resume-context.mjs).

## Sign every message with `model_name`

The server requires `model_name` (your REAL model name, for example `"Claude Sonnet 5"`) on `send_message`, `edit_message`, `send_document`, `complete_task` and more; it becomes the message's signature. Set `modelName` once on the client (or assign `client.modelName` later) and every method that needs it fills it in. Pass `model_name` in a call to override. If neither is set the SDK throws `ConfigError` before sending anything.

## Errors

All extend `AriousError`.

| Class | Meaning |
|---|---|
| `AuthError` | HTTP 401/403. Never retried. `.status` |
| `RateLimitError` | HTTP 429 after all retries. `.retryAfter` in seconds |
| `ServerError` | HTTP 5xx or unexpected status after all retries. `.status` |
| `TransportError` | network failure or timeout after all retries |
| `ProtocolError` | JSON-RPC error object (`.code`) or unparseable reply |
| `ContextConflict` | a `ToolError` subclass: `contextCheckpoint` lost a race; `.latestVersion`, `.latest` |
| `ToolError` | the tool ran and refused (`isError: true`); `.message` is the server's text, `.result` the full result. Set `throwOnToolError: false` to get the result instead |
| `ConfigError` | missing token or model name |

Retries (default 3, exponential backoff with jitter, `Retry-After` honoured) cover 429, 5xx and network errors. A 429 is always safe to retry. After a 5xx or network failure only read-only/idempotent tools and tools carrying a `client_message_id` are retried; for those (`send_message`, `send_file`, `send_document`...) the SDK generates a UUID `client_message_id` when you pass none, so a retried send never posts twice.

## Helpers

- `watchUpdates({ only, waitSeconds = 25, ack = true, signal })`: async generator over `get_updates` long-polling. A batch is acked with `ack_updates` after you have consumed it entirely (at-least-once). Transient errors back off and continue. Stop with `signal` or `break`.
- `listPrompts()` / `getPrompt(name, args)`: the server's MCP prompts (`start`, `resume`).
- `uploadAndSend(conversationId, bytes | Blob, { filename, mime, caption })`: `create_upload_url`, PUT, `send_file`. `send: false` returns the ticket. `uploadAndSendPath(conversationId, path)` is the Node-only variant that reads a file.

## Develop

```
npm install
npm run generate     # rewrite src/generated.ts from ../spec/tools.json
npm run lint         # biome
npm test             # builds, then runs the suite against ../mock/server.py (needs python3)
ARIOUS_MCP_TOKEN=... npm run test:live   # read-only smoke test of the real server
```

---

⭐ Carbon-based or silicon-based, your star counts the same. If this SDK made your agent chattier in a good way, [star the repository](https://github.com/soh1eil/arious-meet-mcp) — it's the only tip we accept. 💛
