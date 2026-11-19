import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

/// Starts the shared Python mock (../mock/server.py) on a free port.
class MockServer {
  MockServer._(this._proc, this.url);
  final Process _proc;
  final String url; // .../v1/mcp

  String get origin => url.replaceFirst('/v1/mcp', '');

  static Future<MockServer> start(
      {String mode = 'json', int failCount = 2}) async {
    final script = File('../mock/server.py').absolute.path;
    final proc = await Process.start('python3', [
      script,
      '--port',
      '0',
      '--mode',
      mode,
      '--fail-count',
      '$failCount',
    ]);
    final ready = Completer<String>();
    proc.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen((l) {
      if (l.startsWith('LISTENING') && !ready.isCompleted) ready.complete(l);
    });
    proc.stderr.drain<void>();
    final first = await ready.future.timeout(const Duration(seconds: 10));
    return MockServer._(proc, first.split(' ').last);
  }

  Future<List<dynamic>> rpcLog() async {
    final r = await http.get(Uri.parse('$origin/__mock/log'));
    return (jsonDecode(r.body) as Map)['log'] as List;
  }

  Future<List<Map<String, dynamic>>> actions() async {
    final r = await http.get(Uri.parse('$origin/__mock/log'));
    return ((jsonDecode(r.body) as Map)['actions'] as List)
        .cast<Map<String, dynamic>>();
  }

  Future<void> push(String token, List<Map<String, dynamic>> items) async {
    await http.post(Uri.parse('$origin/__mock/push'),
        body: jsonEncode({'token': token, 'items': items}));
  }

  Future<void> control(String path, Map<String, dynamic> body) async {
    await http.post(Uri.parse('$origin$path'), body: jsonEncode(body));
  }

  Future<void> stop() async {
    _proc.kill();
    await _proc.exitCode;
  }
}

int _n = 0;
String uniqueToken() =>
    'test-dart-${DateTime.now().microsecondsSinceEpoch}-${_n++}';
