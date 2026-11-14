import 'dart:convert';

/// Parses a Server-Sent-Events body and returns every `data:` payload
/// (multi-line data fields are joined with newlines, per the SSE spec).
List<String> parseSseData(String body) {
  final out = <String>[];
  var buf = <String>[];
  void flush() {
    if (buf.isNotEmpty) {
      out.add(buf.join('\n'));
      buf = <String>[];
    }
  }

  for (final raw in const LineSplitter().convert(body)) {
    if (raw.isEmpty) {
      flush();
    } else if (raw.startsWith(':')) {
      continue;
    } else if (raw.startsWith('data:')) {
      var v = raw.substring(5);
      if (v.startsWith(' ')) v = v.substring(1);
      buf.add(v);
    }
  }
  flush();
  return out;
}

/// One decoded SSE event from a live stream.
class SseEvent {
  SseEvent(this.data);
  final String data;
}

/// Incrementally turns text chunks into [SseEvent]s.
Stream<SseEvent> sseEvents(Stream<String> chunks) async* {
  var pending = '';
  var data = <String>[];
  await for (final chunk in chunks) {
    pending += chunk;
    while (true) {
      final i = pending.indexOf('\n');
      if (i < 0) break;
      var line = pending.substring(0, i);
      pending = pending.substring(i + 1);
      if (line.endsWith('\r')) line = line.substring(0, line.length - 1);
      if (line.isEmpty) {
        if (data.isNotEmpty) {
          yield SseEvent(data.join('\n'));
          data = <String>[];
        }
      } else if (line.startsWith('data:')) {
        var v = line.substring(5);
        if (v.startsWith(' ')) v = v.substring(1);
        data.add(v);
      }
    }
  }
}
