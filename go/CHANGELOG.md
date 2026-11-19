# Changelog

## 0.3.0

- Catalogue regenerated from the live server: 143 tools. New: `context_list`, `context_search`, `context_get`, `context_resume`, `context_create`, `context_checkpoint`, `context_set_status` (Arious Context; all take an optional `organization_id`), `start_here`, and the office tools `list_cartable`, `get_letter`, `draft_letter`, `suggest_referral`, `summarize_letter`, `search_archive`, `extract_letter_scan`, `get_office_report`.
- Changed tools: `ack_updates` takes `update_ids` (platform updates) and `cursor` is now optional; `get_handbook` sections `office` and `context`; `send_widget` description.
- Typed results: `DecodeContextResume`, `DecodeCheckpoint` (with `Redaction`, `ContextVersion`), `DecodeStartHere` (with `PlatformUpdate`); `ToolResult.ContextReminder()` and `ToolResult.PlatformUpdates()`.
- `*ContextConflictError` (unwraps to `*ToolError`; `IsContextConflict`) is returned when `ContextCheckpoint` answers `conflict: true`; it carries `BaseVersion`, `LatestVersion` and `Latest`.
- Prompts: `ListPrompts(ctx)` and `GetPrompt(ctx, name, args)`.
- Example `examples/resume/main.go`; README section on Arious Context.
