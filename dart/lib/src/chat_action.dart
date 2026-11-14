import 'client.dart';

/// What the agent is doing, for `sendChatAction` and the optional `action` of
/// `sendTyping`.
///
/// The notice fades after about 5 seconds: repeat it about every 4 seconds
/// while the work goes on. [cancel] clears it at once.
enum ChatAction {
  typing('typing'),
  uploadPhoto('upload_photo'),
  uploadVideo('upload_video'),
  recordVoice('record_voice'),
  uploadVoice('upload_voice'),
  uploadDocument('upload_document'),
  recordVideoNote('record_video_note'),
  uploadVideoNote('upload_video_note'),
  chooseSticker('choose_sticker'),
  findLocation('find_location'),
  cancel('cancel');

  const ChatAction(this.wire);

  /// The name the server uses (`upload_photo`...).
  final String wire;
}

/// One `search_gifs` result. [previewUrl] is a link on the server, valid for
/// about an hour.
class Gif {
  const Gif({
    required this.gifId,
    required this.title,
    required this.width,
    required this.height,
    required this.contentType,
    required this.source,
    this.previewUrl,
  });

  factory Gif.fromJson(Map<String, dynamic> j) => Gif(
        gifId: (j['gif_id'] ?? '') as String,
        title: (j['title'] ?? '') as String,
        width: (j['width'] ?? 0) as int,
        height: (j['height'] ?? 0) as int,
        contentType: (j['content_type'] ?? '') as String,
        source: (j['source'] ?? '') as String,
        previewUrl: j['preview_url'] as String?,
      );

  final String gifId;
  final String title;
  final int width;
  final int height;
  final String contentType;
  final String source;
  final String? previewUrl;
}

/// Typed view of a `search_gifs` result. [busy] means the live GIF source was
/// busy and the list may be shorter than usual.
class SearchGifsResult {
  const SearchGifsResult({required this.gifs, this.busy = false});

  /// Reads the structured content of a `searchGifs` result.
  factory SearchGifsResult.fromResult(ToolResult r) {
    final s = r.structured;
    if (s == null) {
      throw ArgumentError('search_gifs result has no structured content');
    }
    return SearchGifsResult(
      gifs: [
        for (final g in (s['gifs'] as List? ?? const []))
          Gif.fromJson(g as Map<String, dynamic>),
      ],
      busy: s['busy'] == true,
    );
  }

  final List<Gif> gifs;
  final bool busy;
}

/// Typed view of a `send_gif` result.
class SendGifResult {
  const SendGifResult({
    required this.messageId,
    required this.conversationId,
    required this.attachmentId,
    required this.gifId,
    this.sentViaGrantName,
  });

  /// Reads the structured content of a `sendGif` result.
  factory SendGifResult.fromResult(ToolResult r) {
    final s = r.structured;
    if (s == null) {
      throw ArgumentError('send_gif result has no structured content');
    }
    return SendGifResult(
      messageId: (s['message_id'] ?? '') as String,
      conversationId: (s['conversation_id'] ?? '') as String,
      attachmentId: (s['attachment_id'] ?? '') as String,
      gifId: (s['gif_id'] ?? '') as String,
      sentViaGrantName: s['sent_via_grant_name'] as String?,
    );
  }

  final String messageId;
  final String conversationId;
  final String attachmentId;
  final String gifId;
  final String? sentViaGrantName;
}
