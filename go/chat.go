package ariousmcp

import "fmt"

// ChatAction is what the agent is doing, for SendChatActionArgs and the
// optional SendTypingArgs.Action. The notice fades after about 5 seconds:
// repeat it about every 4 seconds while the work goes on. ChatActionCancel
// clears it at once.
type ChatAction string

// The chat actions the server accepts.
const (
	ChatActionTyping          ChatAction = "typing"
	ChatActionUploadPhoto     ChatAction = "upload_photo"
	ChatActionUploadVideo     ChatAction = "upload_video"
	ChatActionRecordVoice     ChatAction = "record_voice"
	ChatActionUploadVoice     ChatAction = "upload_voice"
	ChatActionUploadDocument  ChatAction = "upload_document"
	ChatActionRecordVideoNote ChatAction = "record_video_note"
	ChatActionUploadVideoNote ChatAction = "upload_video_note"
	ChatActionChooseSticker   ChatAction = "choose_sticker"
	ChatActionFindLocation    ChatAction = "find_location"
	ChatActionCancel          ChatAction = "cancel"
)

// ChatActions lists every valid ChatAction.
func ChatActions() []ChatAction {
	return []ChatAction{
		ChatActionTyping, ChatActionUploadPhoto, ChatActionUploadVideo, ChatActionRecordVoice,
		ChatActionUploadVoice, ChatActionUploadDocument, ChatActionRecordVideoNote,
		ChatActionUploadVideoNote, ChatActionChooseSticker, ChatActionFindLocation, ChatActionCancel,
	}
}

// Valid reports whether a is one of the actions the server knows.
func (a ChatAction) Valid() bool {
	for _, v := range ChatActions() {
		if a == v {
			return true
		}
	}
	return false
}

// String implements fmt.Stringer.
func (a ChatAction) String() string { return string(a) }

// Gif is one search_gifs result. PreviewURL is a link on the server, valid for
// about an hour.
type Gif struct {
	GifID       string `json:"gif_id"`
	Title       string `json:"title"`
	Width       int64  `json:"width"`
	Height      int64  `json:"height"`
	ContentType string `json:"content_type"`
	Source      string `json:"source"`
	PreviewURL  string `json:"preview_url,omitempty"`
}

// SearchGifsResult is the structured result of search_gifs. Busy is true when
// the live GIF source was busy and the list may be shorter than usual.
type SearchGifsResult struct {
	Gifs []Gif `json:"gifs"`
	Busy bool  `json:"busy,omitempty"`
}

// SendGifResult is the structured result of send_gif.
type SendGifResult struct {
	MessageID        string `json:"message_id"`
	ConversationID   string `json:"conversation_id"`
	AttachmentID     string `json:"attachment_id"`
	GifID            string `json:"gif_id"`
	SentViaGrantName string `json:"sent_via_grant_name,omitempty"`
}

// DecodeSearchGifs reads the typed result of a SearchGifs call.
func DecodeSearchGifs(r *ToolResult) (*SearchGifsResult, error) {
	var out SearchGifsResult
	if err := r.Decode(&out); err != nil {
		return nil, fmt.Errorf("ariousmcp: decode search_gifs result: %w", err)
	}
	return &out, nil
}

// DecodeSendGif reads the typed result of a SendGif call.
func DecodeSendGif(r *ToolResult) (*SendGifResult, error) {
	var out SendGifResult
	if err := r.Decode(&out); err != nil {
		return nil, fmt.Errorf("ariousmcp: decode send_gif result: %w", err)
	}
	return &out, nil
}
