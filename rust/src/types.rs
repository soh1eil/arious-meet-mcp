//! Typed models for the chat-action and GIF tools.

use serde::{Deserialize, Serialize};

/// What the agent is doing, for [`Client::send_chat_action`](crate::Client::send_chat_action) and the
/// optional `action` of [`SendTypingOpts`](crate::SendTypingOpts).
///
/// The notice fades after about 5 seconds: repeat it about every 4 seconds while the work goes on.
/// [`ChatAction::Cancel`] clears it at once.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChatAction {
    Typing,
    UploadPhoto,
    UploadVideo,
    RecordVoice,
    UploadVoice,
    UploadDocument,
    RecordVideoNote,
    UploadVideoNote,
    ChooseSticker,
    FindLocation,
    Cancel,
}

impl ChatAction {
    /// Every action, in the server's order.
    pub const ALL: [ChatAction; 11] = [
        ChatAction::Typing,
        ChatAction::UploadPhoto,
        ChatAction::UploadVideo,
        ChatAction::RecordVoice,
        ChatAction::UploadVoice,
        ChatAction::UploadDocument,
        ChatAction::RecordVideoNote,
        ChatAction::UploadVideoNote,
        ChatAction::ChooseSticker,
        ChatAction::FindLocation,
        ChatAction::Cancel,
    ];

    /// The name the server uses (`upload_photo`...).
    pub fn as_wire(self) -> &'static str {
        match self {
            ChatAction::Typing => "typing",
            ChatAction::UploadPhoto => "upload_photo",
            ChatAction::UploadVideo => "upload_video",
            ChatAction::RecordVoice => "record_voice",
            ChatAction::UploadVoice => "upload_voice",
            ChatAction::UploadDocument => "upload_document",
            ChatAction::RecordVideoNote => "record_video_note",
            ChatAction::UploadVideoNote => "upload_video_note",
            ChatAction::ChooseSticker => "choose_sticker",
            ChatAction::FindLocation => "find_location",
            ChatAction::Cancel => "cancel",
        }
    }
}

/// One `search_gifs` result. `preview_url` is a link on the server, valid for about an hour.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct Gif {
    pub gif_id: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub width: i64,
    #[serde(default)]
    pub height: i64,
    #[serde(default)]
    pub content_type: String,
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub preview_url: Option<String>,
}

/// Structured result of `search_gifs`; read it with
/// [`ToolResult::decode`](crate::ToolResult::decode). `busy` is true when the live GIF source was busy.
#[derive(Debug, Clone, PartialEq, Default, Deserialize)]
pub struct SearchGifsResult {
    #[serde(default)]
    pub gifs: Vec<Gif>,
    #[serde(default)]
    pub busy: bool,
}

/// Structured result of `send_gif`; read it with [`ToolResult::decode`](crate::ToolResult::decode).
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct SendGifResult {
    pub message_id: String,
    pub conversation_id: String,
    pub attachment_id: String,
    pub gif_id: String,
    #[serde(default)]
    pub sent_via_grant_name: Option<String>,
}
