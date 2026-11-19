# Changelog

## 0.3.0

- Catalogue regenerated from the live server: 143 tools. New: `context_list`, `context_search`, `context_get`, `context_resume`, `context_create`, `context_checkpoint`, `context_set_status` (Arious Context; all take an optional `organization_id`), `start_here`, and the office tools `list_cartable`, `get_letter`, `draft_letter`, `suggest_referral`, `summarize_letter`, `search_archive`, `extract_letter_scan`, `get_office_report`.
- Changed tools: `ack_updates` takes `update_ids` (platform updates) and `cursor` is now optional; `get_handbook` sections `office` and `context`; `send_widget` description.
- Typed results: `contextResume` returns `ContextResumeResult`, `contextCheckpoint` `CheckpointResult` (with `Redaction`), `startHere` `StartHereResult` (with `PlatformUpdate`); `ToolResult.contextReminder`; `isCheckpointConflict` type guard.
- `ContextConflict` (a `ToolError`) is thrown when `contextCheckpoint` answers `conflict: true`; it carries `baseVersion`, `latestVersion` and `latest`.
- Prompts: `listPrompts()` and `getPrompt(name, args)`.
- Example `examples/resume-context.mjs`; README section on Arious Context.
