## 0.3.0

- Catalogue regenerated from the live server: 143 tools. New: `context_list`, `context_search`, `context_get`, `context_resume`, `context_create`, `context_checkpoint`, `context_set_status` (Arious Context; all take an optional `organization_id`), `start_here`, and the office tools `list_cartable`, `get_letter`, `draft_letter`, `suggest_referral`, `summarize_letter`, `search_archive`, `extract_letter_scan`, `get_office_report`.
- Changed tools: `ack_updates` takes `update_ids` (platform updates) and `cursor` is now optional, so `ack_updates(cursor)` is now `ack_updates(AckUpdatesOpts { cursor: Some(..), ..Default::default() })` (breaking); `get_handbook` sections `office` and `context`; `send_widget` description.
- Typed results: `ContextResume`, `CheckpointResult` (with `Redaction`, `ContextVersion`), `StartHere` (with `PlatformUpdate`) via `ToolResult::decode`; `ToolResult::context_reminder()` and `ToolResult::platform_updates()`.
- `Error::ContextConflict` is returned when `context_checkpoint` answers `conflict: true`; it carries `base_version`, `latest_version` and `latest`.
- Prompts: `list_prompts()` and `get_prompt(name, arguments)`.
- Example `examples/resume_context.rs`; README section on Arious Context.

# Changelog

## 0.2.0

- `send_chat_action(ChatAction, conversation_id)`, and `send_typing_with(conversation_id, SendTypingOpts { action })` (`send_typing(conversation_id)` keeps its signature).
- `ChatAction` enum; `search_gifs` / `send_gif` with typed results `SearchGifsResult` / `SendGifResult` via `ToolResult::decode`.
- 127 generated tool wrappers.

## 0.1.0

- Initial release: client, 124 generated tool wrappers, helpers.
