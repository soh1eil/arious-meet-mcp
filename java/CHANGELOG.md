# Changelog

## 0.3.0

- Catalogue regenerated from the live server: 143 tools. New: `contextList`, `contextSearch`, `contextGet`, `contextResume`, `contextCreate`, `contextCheckpoint`, `contextSetStatus` (Arious Context; all take an optional `organization_id`), `startHere`, and the office tools `listCartable`, `getLetter`, `draftLetter`, `suggestReferral`, `summarizeLetter`, `searchArchive`, `extractLetterScan`, `getOfficeReport`.
- Changed tools: `ackUpdates` takes `update_ids` (platform updates) and `cursor` is now optional, so the old `ackUpdates(String cursor)` is now `ackUpdates(Map.of("cursor", cursor))`; `getHandbook` sections `office` and `context`; `sendWidget` description.
- Typed results: `ContextResume`, `CheckpointResult` (with `Redaction`, `ContextVersion`), `StartHere` (with `PlatformUpdate`); `ToolResult.contextReminder()` and `ToolResult.platformUpdates()`.
- `McpException.ContextConflict` (a `McpException.Tool`) is thrown when `contextCheckpoint` answers `conflict: true`; it carries `baseVersion()`, `latestVersion()` and `latest()`. `McpException.Tool` is no longer final and carries the refused `result()`.
- Prompts: `listPrompts()` and `getPrompt(name, arguments)`.
- Example `examples/ResumeContext.java`; README section on Arious Context.

## 0.2.0

- `sendChatAction(ChatAction, conversationId)` and `sendTyping(conversationId, ChatAction)` with a `ChatAction` enum.
- `searchGifs` / `sendGif` with typed results `SearchGifsResult.from(...)` / `SendGifResult.from(...)`.
- 127 generated tool wrappers.

## 0.1.0

- Initial release: client, 124 generated tool wrappers, helpers.
