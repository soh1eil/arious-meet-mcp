import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;
import 'dart:math';

import 'package:http/http.dart' as http;

import 'errors.dart';
import 'sse.dart';
import 'tools.g.dart' show toolTraits;

const String defaultBaseUrl = 'https://api.ariousmeet.com/v1/mcp';
const String protocolVersion = '2025-06-18';
const String sdkVersion = '0.2.0';

/// The decoded result of a `tools/call`.
class ToolResult {
  ToolResult({
    required this.text,
    required this.content,
    this.structured,
    this.isError = false,
  });

  /// Text of the first text block (what a human would read).
  final String text;

  /// Every content block, as sent by the server.
  final List<Map<String, dynamic>> content;

  /// `structuredContent`, when the tool provides it.
  final Map<String, dynamic>? structured;
  final bool isError;

  /// Structured content if present, otherwise the text parsed as JSON when it
  /// is JSON, otherwise the raw text.
  Object? get data {
    if (structured != null) return structured;
    try {
      return jsonDecode(text);
    } on FormatException {
      return text;
    }
  }
}

/// Low-level Arious Meet MCP client.
///
/// Never logs or prints the token. Retries 429 always, and 5xx / network
/// failures only when the call is safe to repeat (read-only/idempotent tool,
/// or carries a `client_message_id`, which this client fills in for tools that
/// accept one).
class McpClient {
  McpClient({
    required String token,
    this.baseUrl = defaultBaseUrl,
    this.modelName,
    this.tokenInPath = false,
    http.Client? httpClient,
    this.timeout = const Duration(seconds: 60),
    this.maxRetries = 3,
    this.backoffBase = const Duration(milliseconds: 500),
    this.clientName = 'arious-meet-mcp-dart',
  })  : _token = token,
        _http = httpClient ?? http.Client(),
        _ownsHttp = httpClient == null {
    if (token.trim().isEmpty) {
      throw ArgumentError('token must not be empty');
    }
  }

  /// Reads the token from `ARIOUS_MCP_TOKEN`.
  factory McpClient.fromEnv({
    String? modelName,
    String? baseUrl,
    http.Client? httpClient,
  }) {
    final t = Platform.environment['ARIOUS_MCP_TOKEN'];
    if (t == null || t.trim().isEmpty) {
      throw McpAuthError('ARIOUS_MCP_TOKEN is not set');
    }
    return McpClient(
      token: t.trim(),
      modelName: modelName,
      baseUrl:
          baseUrl ?? Platform.environment['ARIOUS_MCP_URL'] ?? defaultBaseUrl,
      httpClient: httpClient,
    );
  }

  final String _token;
  final String baseUrl;

  /// Default `model_name` for every tool that takes one.
  String? modelName;

  /// Use the `/t/{token}` URL form instead of the Authorization header.
  final bool tokenInPath;
  final Duration timeout;
  final int maxRetries;
  final Duration backoffBase;
  final String clientName;
  final http.Client _http;
  final bool _ownsHttp;

  int _id = 0;
  String? _sessionId;
  Future<Map<String, dynamic>>? _init;
  Map<String, dynamic>? serverInfo;

  /// Tool name -> schema facts, filled by the generated code.
  Map<String, ToolTraits> traits = toolTraits;

  @override
  String toString() => 'McpClient($baseUrl)';

  Uri get _uri => tokenInPath
      ? Uri.parse('${baseUrl.replaceAll(RegExp(r'/+$'), '')}/t/$_token/')
      : Uri.parse(baseUrl);

  Map<String, String> _headers({bool sse = false}) => {
        'Content-Type': 'application/json',
        'Accept':
            sse ? 'text/event-stream' : 'application/json, text/event-stream',
        'User-Agent': '$clientName/$sdkVersion',
        'MCP-Protocol-Version': protocolVersion,
        if (!tokenInPath) 'Authorization': 'Bearer $_token',
        if (_sessionId != null) 'Mcp-Session-Id': _sessionId!,
      };

  /// Performs the `initialize` handshake (once; later calls return the cache).
  Future<Map<String, dynamic>> initialize() => _init ??= _doInit();

  Future<Map<String, dynamic>> _doInit() async {
    try {
      final res = await _rpc(
          'initialize',
          {
            'protocolVersion': protocolVersion,
            'capabilities': <String, dynamic>{},
            'clientInfo': {'name': clientName, 'version': sdkVersion},
          },
          retry: true);
      await _notify('notifications/initialized');
      serverInfo = (res['serverInfo'] as Map?)?.cast<String, dynamic>();
      return res;
    } catch (_) {
      _init = null;
      rethrow;
    }
  }

  /// `tools/list`.
  Future<List<Map<String, dynamic>>> listTools() async {
    await initialize();
    final res = await _rpc('tools/list', <String, dynamic>{}, retry: true);
    return ((res['tools'] as List?) ?? const [])
        .map((e) => (e as Map).cast<String, dynamic>())
        .toList();
  }

  /// `ping`.
  Future<void> ping() async {
    await initialize();
    await _rpc('ping', <String, dynamic>{}, retry: true);
  }

  /// `tools/call`. Throws [McpToolError] when the tool answers `isError`
  /// (pass `throwOnError: false` to get the [ToolResult] instead).
  Future<ToolResult> callTool(
    String name, [
    Map<String, dynamic>? arguments,
    bool throwOnError = true,
  ]) async {
    await initialize();
    final args = <String, dynamic>{...?arguments}
      ..removeWhere((_, v) => v == null);
    final t = traits[name];
    var safe = t?.safeToRepeat ?? false;
    if (t != null) {
      if (t.hasModelName && args['model_name'] == null && modelName != null) {
        args['model_name'] = modelName;
      }
      if (t.requiresModelName && args['model_name'] == null) {
        throw ArgumentError(
            'model_name is required by $name: pass it or set McpClient.modelName');
      }
      if (t.hasClientMessageId) {
        args['client_message_id'] ??= _uuid();
        safe = true;
      }
    }
    if (args.containsKey('client_message_id')) safe = true;
    final res = await _rpc('tools/call', {'name': name, 'arguments': args},
        retry: safe);
    final blocks = ((res['content'] as List?) ?? const [])
        .map((e) => (e as Map).cast<String, dynamic>())
        .toList();
    final text = blocks
        .where((b) => b['type'] == 'text')
        .map((b) => (b['text'] ?? '').toString())
        .firstWhere((_) => true, orElse: () => '');
    final out = ToolResult(
      text: text,
      content: blocks,
      structured: (res['structuredContent'] as Map?)?.cast<String, dynamic>(),
      isError: res['isError'] == true,
    );
    if (out.isError && throwOnError) {
      throw McpToolError(text, tool: name, result: res);
    }
    return out;
  }

  /// Opens the server -> client SSE stream (`GET`) and yields each JSON-RPC
  /// notification. Ends when the server closes the stream.
  Stream<Map<String, dynamic>> notifications({String? conversationId}) async* {
    await initialize();
    final uri = conversationId == null
        ? _uri
        : _uri.replace(queryParameters: {'conversation_id': conversationId});
    final req = http.Request('GET', uri)
      ..headers.addAll(_headers(sse: true))
      ..headers.remove('Content-Type');
    final resp = await _http.send(req).timeout(timeout);
    if (resp.statusCode != 200) {
      final body = await resp.stream.bytesToString();
      throw _statusError(resp.statusCode, body, resp.headers);
    }
    final text = resp.stream.transform(utf8.decoder);
    await for (final ev in sseEvents(text)) {
      try {
        final m = jsonDecode(ev.data);
        if (m is Map<String, dynamic>) yield m;
      } on FormatException {
        continue;
      }
    }
  }

  /// PUTs raw bytes to an absolute URL (used for `create_upload_url` tickets;
  /// the ticket URL carries its own credential, so no bearer header is sent).
  Future<void> putBytes(
    String url,
    List<int> bytes, {
    Map<String, String> headers = const {},
  }) async {
    var attempt = 0;
    while (true) {
      http.Response? resp;
      try {
        resp = await _http
            .put(Uri.parse(url), headers: headers, body: bytes)
            .timeout(timeout * 5);
      } on Exception catch (e) {
        if (attempt >= maxRetries) {
          throw McpTransportError('upload failed: ${e.runtimeType}');
        }
      }
      if (resp != null) {
        if (resp.statusCode < 300) return;
        final retryable = resp.statusCode == 429 || resp.statusCode >= 500;
        if (!retryable || attempt >= maxRetries) {
          throw _statusError(resp.statusCode, resp.body, resp.headers);
        }
      }
      await Future<void>.delayed(_delay(attempt, null));
      attempt++;
    }
  }

  /// Releases the underlying HTTP client (only if this object created it).
  void close() {
    if (_ownsHttp) _http.close();
  }

  // ---------------------------------------------------------------- internals

  Future<void> _notify(String method) async {
    final resp = await _send({'jsonrpc': '2.0', 'method': method}, retry: true);
    if (resp.statusCode >= 400) {
      throw _statusError(resp.statusCode, resp.body, resp.headers);
    }
  }

  Future<Map<String, dynamic>> _rpc(
    String method,
    Map<String, dynamic> params, {
    required bool retry,
  }) async {
    final id = ++_id;
    final body = {
      'jsonrpc': '2.0',
      'id': id,
      'method': method,
      'params': params
    };
    final resp = await _send(body, retry: retry);
    if (resp.statusCode >= 400) {
      throw _statusError(resp.statusCode, resp.body, resp.headers);
    }
    final sid = resp.headers['mcp-session-id'];
    if (sid != null && sid.isNotEmpty && method == 'initialize') {
      _sessionId = sid;
    }
    final msg = _decode(resp, id);
    final err = msg['error'];
    if (err is Map) {
      throw McpProtocolError((err['message'] ?? 'protocol error').toString(),
          code: err['code'] is int ? err['code'] as int : null);
    }
    final result = msg['result'];
    if (result is! Map) {
      throw McpProtocolError('response has neither result nor error');
    }
    return result.cast<String, dynamic>();
  }

  Map<String, dynamic> _decode(http.Response resp, int id) {
    final ct = (resp.headers['content-type'] ?? '').toLowerCase();
    final text = utf8.decode(resp.bodyBytes);
    List<Object?> candidates;
    if (ct.contains('text/event-stream')) {
      candidates = parseSseData(text).map((s) {
        try {
          return jsonDecode(s);
        } on FormatException {
          return null;
        }
      }).toList();
    } else {
      try {
        final d = jsonDecode(text);
        candidates = d is List ? d : [d];
      } on FormatException {
        throw McpTransportError(
            'server returned a non-JSON body (HTTP ${resp.statusCode})',
            status: resp.statusCode);
      }
    }
    Map<String, dynamic>? fallback;
    for (final c in candidates) {
      if (c is Map<String, dynamic> &&
          (c.containsKey('result') || c.containsKey('error'))) {
        if (c['id'] == id) return c;
        fallback ??= c;
      }
    }
    if (fallback != null) return fallback;
    throw McpProtocolError('no JSON-RPC response in server reply');
  }

  Future<http.Response> _send(Map<String, dynamic> body,
      {required bool retry}) async {
    final payload = jsonEncode(body);
    var attempt = 0;
    while (true) {
      http.Response? resp;
      Object? netErr;
      try {
        resp = await _http
            .post(_uri, headers: _headers(), body: payload)
            .timeout(timeout);
      } on TimeoutException catch (e) {
        netErr = e;
      } on http.ClientException catch (e) {
        netErr = e;
      } on Exception catch (e) {
        // SocketException, HandshakeException, ...
        netErr = e;
      }
      if (resp != null) {
        final s = resp.statusCode;
        final retryable = s == 429 || (retry && s >= 500 && s != 501);
        if (!retryable || attempt >= maxRetries) return resp;
        await Future<void>.delayed(
            _delay(attempt, _retryAfter(resp.headers['retry-after'])));
      } else {
        if (!retry || attempt >= maxRetries) {
          throw McpTransportError(netErr is TimeoutException
              ? 'request timed out after ${timeout.inSeconds}s'
              : 'network error: ${netErr.runtimeType}');
        }
        await Future<void>.delayed(_delay(attempt, null));
      }
      attempt++;
    }
  }

  Duration _delay(int attempt, Duration? hint) {
    if (hint != null) {
      return hint > const Duration(seconds: 30)
          ? const Duration(seconds: 30)
          : hint;
    }
    final ms = backoffBase.inMilliseconds * (1 << attempt);
    final jitter = _rng.nextInt(max(1, ms ~/ 4));
    return Duration(milliseconds: min(ms + jitter, 20000));
  }

  static final Random _rng = Random();

  static Duration? _retryAfter(String? v) {
    if (v == null) return null;
    final s = int.tryParse(v.trim());
    return s == null ? null : Duration(seconds: s);
  }

  McpException _statusError(
      int status, String body, Map<String, String> headers) {
    var detail = body.length > 300 ? body.substring(0, 300) : body;
    try {
      final j = jsonDecode(body);
      if (j is Map) {
        detail = (j['error'] ?? j['message'] ?? detail).toString();
        if (j['error'] is Map) {
          detail = ((j['error'] as Map)['message'] ?? detail).toString();
        }
      }
    } on FormatException {
      // keep raw detail
    }
    if (status == 401 || status == 403) {
      return McpAuthError('authentication failed (HTTP $status): $detail',
          status: status);
    }
    if (status == 429) {
      return McpRateLimitError('rate limited (HTTP 429): $detail',
          retryAfter: _retryAfter(headers['retry-after']));
    }
    return McpTransportError('HTTP $status: $detail', status: status);
  }

  static String _uuid() {
    final r = Random.secure();
    final b = List<int>.generate(16, (_) => r.nextInt(256));
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    String h(int i) => b[i].toRadixString(16).padLeft(2, '0');
    return '${h(0)}${h(1)}${h(2)}${h(3)}-${h(4)}${h(5)}-${h(6)}${h(7)}-'
        '${h(8)}${h(9)}-${h(10)}${h(11)}${h(12)}${h(13)}${h(14)}${h(15)}';
  }
}

/// Schema facts the client needs per tool (generated).
class ToolTraits {
  const ToolTraits({
    this.hasModelName = false,
    this.requiresModelName = false,
    this.hasClientMessageId = false,
    this.safeToRepeat = false,
  });
  final bool hasModelName;
  final bool requiresModelName;
  final bool hasClientMessageId;
  final bool safeToRepeat;
}
