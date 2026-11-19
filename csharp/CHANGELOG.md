## 0.3.0

- Catalogue regenerated from the live server: 143 tools. New: `ContextListAsync`, `ContextSearchAsync`, `ContextGetAsync`, `ContextResumeAsync`, `ContextCreateAsync`, `ContextCheckpointAsync`, `ContextSetStatusAsync` (Arious Context; all take an optional `organizationId`), `StartHereAsync`, and the office tools `ListCartableAsync`, `GetLetterAsync`, `DraftLetterAsync`, `SuggestReferralAsync`, `SummarizeLetterAsync`, `SearchArchiveAsync`, `ExtractLetterScanAsync`, `GetOfficeReportAsync`.
- Changed tools: `AckUpdatesAsync` takes `updateIds` (platform updates) and `cursor` is now an optional named parameter, so `AckUpdatesAsync(cursor)` still compiles but `AckUpdatesAsync(cursor, ct)` must name `ct:` (breaking); `GetHandbookAsync` sections `office` and `context`; `SendWidgetAsync` description.
- Typed results: `ContextResume`, `CheckpointResult` (with `Redaction`, `ContextVersion`), `StartHere` (with `PlatformUpdate`), all via `From`; `ToolResult.ContextReminder` and `ToolResult.PlatformUpdates`.
- `ContextConflictException` (a `McpToolException`) is thrown when `ContextCheckpointAsync` answers `conflict: true`; it carries `BaseVersion`, `LatestVersion` and `Latest`. `McpToolException` is no longer sealed and carries the refused `Result`.
- Prompts: `ListPromptsAsync()` and `GetPromptAsync(name, arguments)`.
- Example `examples/ResumeContext.cs.txt`; README section on Arious Context.

# Changelog

## 0.2.0

- `SendChatActionAsync` and the optional `action` of `SendTypingAsync`, with a `ChatAction` enum (`ToWire()`).
- `SearchGifsAsync` / `SendGifAsync` with typed results `SearchGifsResult.From(...)` / `SendGifResult.From(...)`.
- 127 generated tool wrappers.

## 0.1.0

- Initial release: client, 124 generated tool wrappers, helpers.
