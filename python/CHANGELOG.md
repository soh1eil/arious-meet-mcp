# Changelog

## 0.3.0

- Catalogue regenerated from the live server: 143 tools. New: `context_list`, `context_search`, `context_get`, `context_resume`, `context_create`, `context_checkpoint`, `context_set_status` (Arious Context; all take an optional `organization_id`), `start_here`, and the office tools `list_cartable`, `get_letter`, `draft_letter`, `suggest_referral`, `summarize_letter`, `search_archive`, `extract_letter_scan`, `get_office_report`.
- Changed tools: `ack_updates` takes `update_ids` (platform updates) and `cursor` is now optional and keyword-only (`ack_updates(cursor=...)`); `get_handbook` sections `office` and `context`; `send_widget` description.
- Typed results: `ContextResume`, `CheckpointResult` (with `Redaction`, `ContextVersion`), `StartHere` (with `PlatformUpdate`); `ToolResult.context_reminder` and `ToolResult.platform_updates`.
- `ContextConflict` (a `ToolError`) is raised when `context_checkpoint` answers `conflict: true`; it carries `base_version`, `latest_version` and `latest`.
- Prompts: `list_prompts()` and `get_prompt(name, arguments)` on `Client` and `AsyncClient`.
- Example `examples/resume_context.py`; README section on Arious Context.
