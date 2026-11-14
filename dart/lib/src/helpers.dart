import 'dart:async';
import 'dart:io';

import 'client.dart';
import 'errors.dart';
import 'tools.g.dart';

/// Higher-level helpers built on the generated tools.
extension AriousHelpers on McpClient {
  /// Long-polls `get_updates` forever and yields each update.
  ///
  /// The cursor is acknowledged (`ack_updates`) only after the consumer has
  /// finished handling a whole batch, i.e. when the stream is asked for the
  /// next element, so a crash mid-batch re-delivers instead of losing items.
  ///
  /// Transient failures (rate limit, network, 5xx) back off and continue;
  /// authentication errors end the stream with the error.
  Stream<Map<String, dynamic>> watchUpdates({
    List<String>? only,
    int waitSeconds = 25,
    Duration idleBackoff = const Duration(seconds: 2),
    bool Function()? shouldStop,
  }) async* {
    String? cursor;
    var failures = 0;
    while (!(shouldStop?.call() ?? false)) {
      ToolResult r;
      try {
        r = await getUpdates(
            only: only, waitSeconds: waitSeconds, cursor: cursor);
        failures = 0;
      } on McpAuthError {
        rethrow;
      } on McpRateLimitError catch (e) {
        await Future<void>.delayed(e.retryAfter ?? idleBackoff);
        continue;
      } on McpTransportError {
        failures++;
        await Future<void>.delayed(idleBackoff * (failures > 5 ? 5 : failures));
        continue;
      }
      final data = r.data;
      if (data is! Map) continue;
      final updates = (data['updates'] as List?) ?? const [];
      final next = data['next_cursor'] as String?;
      for (final u in updates) {
        if (u is Map) yield u.cast<String, dynamic>();
      }
      if (next != null && next.isNotEmpty) {
        if (updates.isNotEmpty) {
          await ackUpdates(cursor: next);
        }
        cursor = next;
      }
    }
  }

  /// Stages [bytes] with `create_upload_url`, PUTs them, and returns the
  /// `upload_id` (usable in `send_message.attachment_ids` or `send_file`).
  Future<String> uploadBytes(
    String conversationId,
    String filename,
    List<int> bytes, {
    String? mime,
  }) async {
    final t = await createUploadUrl(
      conversationId: conversationId,
      filename: filename,
      size: bytes.length,
      mime: mime,
    );
    final d = t.structured;
    final url = d?['upload_url'];
    final id = d?['upload_id'];
    if (url is! String || id is! String) {
      throw McpProtocolError(
          'create_upload_url returned no upload_url/upload_id');
    }
    final headers = <String, String>{
      for (final e in ((d?['headers'] as Map?) ?? const {}).entries)
        e.key.toString(): e.value.toString(),
    };
    await putBytes(url, bytes, headers: headers);
    return id;
  }

  /// Uploads a local file and sends it as its own message. Returns the
  /// `send_file` result.
  Future<ToolResult> uploadFile(
    String conversationId,
    String path, {
    String? caption,
    String? mime,
    String? replyToId,
    String? modelName,
  }) async {
    final f = File(path);
    final bytes = await f.readAsBytes();
    final name = f.uri.pathSegments.last;
    final id = await uploadBytes(conversationId, name, bytes, mime: mime);
    return sendFile(
      conversationId: conversationId,
      uploadId: id,
      caption: caption,
      replyToId: replyToId,
      modelName: modelName,
    );
  }
}
