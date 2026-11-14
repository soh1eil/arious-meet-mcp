using System.Text.Json.Nodes;

namespace AriousMeet.Mcp;

/// <summary>
/// What the agent is doing, for <c>SendChatActionAsync</c> and the optional <c>action</c> of
/// <c>SendTypingAsync</c>. The notice fades after about 5 seconds: repeat it about every 4 seconds while
/// the work goes on. <see cref="Cancel"/> clears it at once.
/// </summary>
public enum ChatAction
{
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

/// <summary>Wire names (<c>upload_photo</c>...) of <see cref="ChatAction"/>.</summary>
public static class ChatActionExtensions
{
    /// <summary>The name the server uses for this action.</summary>
    public static string ToWire(this ChatAction action) => action switch
    {
        ChatAction.Typing => "typing",
        ChatAction.UploadPhoto => "upload_photo",
        ChatAction.UploadVideo => "upload_video",
        ChatAction.RecordVoice => "record_voice",
        ChatAction.UploadVoice => "upload_voice",
        ChatAction.UploadDocument => "upload_document",
        ChatAction.RecordVideoNote => "record_video_note",
        ChatAction.UploadVideoNote => "upload_video_note",
        ChatAction.ChooseSticker => "choose_sticker",
        ChatAction.FindLocation => "find_location",
        ChatAction.Cancel => "cancel",
        _ => throw new ArgumentOutOfRangeException(nameof(action), action, "unknown chat action"),
    };
}

public sealed partial class McpClient
{
    internal static void Put(JsonObject o, string key, ChatAction? value)
    {
        if (value is { } v)
        {
            o[key] = v.ToWire();
        }
    }
}

/// <summary>One <c>search_gifs</c> result. <see cref="PreviewUrl"/> is valid for about an hour.</summary>
public sealed record Gif(
    string GifId,
    string Title,
    long Width,
    long Height,
    string ContentType,
    string Source,
    string? PreviewUrl);

/// <summary>Typed view of a <c>search_gifs</c> result; <see cref="Busy"/> means the live GIF source was busy.</summary>
public sealed record SearchGifsResult(IReadOnlyList<Gif> Gifs, bool Busy)
{
    /// <summary>Reads the structured content of a <c>SearchGifsAsync</c> result.</summary>
    public static SearchGifsResult From(ToolResult result)
    {
        var o = result.Structured ?? throw new InvalidOperationException("search_gifs result has no structured content");
        var gifs = new List<Gif>();
        if (o["gifs"] is JsonArray arr)
        {
            foreach (var n in arr.OfType<JsonObject>())
            {
                gifs.Add(new Gif(
                    (string?)n["gif_id"] ?? "",
                    (string?)n["title"] ?? "",
                    (long?)n["width"] ?? 0,
                    (long?)n["height"] ?? 0,
                    (string?)n["content_type"] ?? "",
                    (string?)n["source"] ?? "",
                    (string?)n["preview_url"]));
            }
        }
        return new SearchGifsResult(gifs, (bool?)o["busy"] ?? false);
    }
}

/// <summary>Typed view of a <c>send_gif</c> result.</summary>
public sealed record SendGifResult(
    string MessageId,
    string ConversationId,
    string AttachmentId,
    string GifId,
    string? SentViaGrantName)
{
    /// <summary>Reads the structured content of a <c>SendGifAsync</c> result.</summary>
    public static SendGifResult From(ToolResult result)
    {
        var o = result.Structured ?? throw new InvalidOperationException("send_gif result has no structured content");
        return new SendGifResult(
            (string?)o["message_id"] ?? "",
            (string?)o["conversation_id"] ?? "",
            (string?)o["attachment_id"] ?? "",
            (string?)o["gif_id"] ?? "",
            (string?)o["sent_via_grant_name"]);
    }
}
