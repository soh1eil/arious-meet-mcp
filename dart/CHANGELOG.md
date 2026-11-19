## 0.3.0

- Catalogue regenerated from the live server: 143 tools. New: `contextList`, `contextSearch`, `contextGet`, `contextResume`, `contextCreate`, `contextCheckpoint`, `contextSetStatus` (Arious Context; all take an optional `organizationId`), `startHere`, and the office tools `listCartable`, `getLetter`, `draftLetter`, `suggestReferral`, `summarizeLetter`, `searchArchive`, `extractLetterScan`, `getOfficeReport`.
- Changed tools: `ackUpdates` takes `updateIds` (platform updates) and `cursor` is now optional (`ackUpdates(cursor: ...)` still works); `getHandbook` sections `office` and `context`; `sendWidget` description.
- Typed results: `ContextResume`, `CheckpointResult` (with `Redaction`, `ContextVersion`), `StartHere` (with `PlatformUpdate`), all via `fromResult`; `ToolResult.contextReminder` and `ToolResult.platformUpdates` (extension).
- `McpContextConflict` (a `McpToolError`) is thrown when `contextCheckpoint` answers `conflict: true`; it carries `baseVersion`, `latestVersion` and `latest`.
- Prompts: `listPrompts()` and `getPrompt(name, arguments)`.
- Example `example/resume_context.dart`; README section on Arious Context.

## 0.2.0

- `sendChatAction` and the optional `action` of `sendTyping`, with a `ChatAction` enum (`.wire`).
- `searchGifs` / `sendGif` with typed results `SearchGifsResult.fromResult(...)` / `SendGifResult.fromResult(...)`.
- 127 generated tool wrappers.

## 0.1.0

- Initial release: client, 124 generated tool wrappers, helpers.
