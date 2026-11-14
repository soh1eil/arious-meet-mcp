# Changelog

## 0.2.0

- `send_chat_action(ChatAction, conversation_id)`, and `send_typing_with(conversation_id, SendTypingOpts { action })` (`send_typing(conversation_id)` keeps its signature).
- `ChatAction` enum; `search_gifs` / `send_gif` with typed results `SearchGifsResult` / `SendGifResult` via `ToolResult::decode`.
- 127 generated tool wrappers.

## 0.1.0

- Initial release: client, 124 generated tool wrappers, helpers.
