import 'dart:convert';

import 'package:arious_meet_mcp/arious_meet_mcp.dart';
import 'package:test/test.dart';

import 'mock_server.dart';

void main() {
  late MockServer json, sse, err500, rl;

  setUpAll(() async {
    json = await MockServer.start();
    sse = await MockServer.start(mode: 'sse');
    err500 = await MockServer.start(mode: 'error');
    rl = await MockServer.start(mode: 'ratelimit');
  });
  tearDownAll(() async {
    await Future.wait([json.stop(), sse.stop(), err500.stop(), rl.stop()]);
  });

  McpClient mk(MockServer s, {String? token, String? model}) => McpClient(
        token: token ?? uniqueToken(),
        baseUrl: s.url,
        modelName: model,
        backoffBase: const Duration(milliseconds: 5),
        timeout: const Duration(seconds: 10),
      );

  for (final mode in ['json', 'sse']) {
    group('mode $mode', () {
      late MockServer s;
      setUp(() => s = mode == 'json' ? json : sse);

      test('initialize and list all 124 tools', () async {
        final c = mk(s);
        final info = await c.initialize();
        expect(info['serverInfo'], isA<Map>());
        final tools = await c.listTools();
        expect(tools.length, 124);
        expect(tools.map((t) => t['name']), containsAll(toolNames));
        c.close();
      });

      test('whoami returns structured content', () async {
        final c = mk(s);
        final r = await c.whoami();
        expect((r.data as Map)['display_name'], 'Mock Agent');
        c.close();
      });

      test('getHandbook returns text only', () async {
        final c = mk(s);
        final r = await c.getHandbook(section: 'tasks');
        expect(r.structured, isNull);
        expect(r.text, contains('tasks'));
        c.close();
      });

      test('searchAppGuide and listOrganizations', () async {
        final c = mk(s);
        final g = await c.searchAppGuide(query: 'calls');
        expect((g.data as Map)['results'], isNotEmpty);
        final o = await c.listOrganizations();
        expect((o.data as Map)['organizations'], isNotEmpty);
        c.close();
      });
    });
  }

  group('errors', () {
    test('bad token gives McpAuthError and never leaks the token', () async {
      final c = mk(json, token: 'wrong-secret-token');
      try {
        await c.whoami();
        fail('should throw');
      } on McpAuthError catch (e) {
        expect(e.status, 401);
        expect(e.toString(), isNot(contains('wrong-secret-token')));
        expect(c.toString(), isNot(contains('wrong-secret-token')));
      }
    });

    test('tool error', () async {
      final c = mk(json);
      expect(
          () => c.callTool('mock_tool_error'),
          throwsA(isA<McpToolError>()
              .having((e) => e.message, 'message', contains('tool-level'))));
      final r = await c.callTool('mock_tool_error', null, false);
      expect(r.isError, isTrue);
    });

    test('protocol error', () async {
      final c = mk(json);
      expect(
          () => c.callTool('mock_protocol_error'),
          throwsA(
              isA<McpProtocolError>().having((e) => e.code, 'code', -32602)));
      expect(() => c.callTool('no_such_tool_at_all'),
          throwsA(isA<McpProtocolError>()));
    });

    test('empty token rejected locally', () {
      expect(() => McpClient(token: ' '), throwsArgumentError);
    });

    test('missing model_name is caught before the network', () async {
      final c = mk(json);
      expect(() => c.sendMessage(conversationId: 'c1', text: 'x'),
          throwsArgumentError);
    });

    test('network error maps to McpTransportError', () async {
      final c = McpClient(
          token: 'test-x',
          baseUrl: 'http://127.0.0.1:1/v1/mcp',
          maxRetries: 1,
          backoffBase: const Duration(milliseconds: 1));
      expect(() => c.whoami(), throwsA(isA<McpTransportError>()));
    });
  });

  group('retries', () {
    test('429 is retried (honouring Retry-After) then succeeds', () async {
      final c = mk(rl);
      final r = await c.whoami();
      expect(r.isError, isFalse);
      final log =
          (await rl.rpcLog()).where((e) => jsonEncode(e).contains('whoami'));
      expect(log.length, greaterThanOrEqualTo(3)); // 2 failures + 1 success
    });

    test('429 gives up with McpRateLimitError when retries run out', () async {
      final c = McpClient(
          token: uniqueToken(),
          baseUrl: rl.url,
          maxRetries: 1,
          backoffBase: const Duration(milliseconds: 1));
      await expectLater(c.whoami(), throwsA(isA<McpRateLimitError>()));
    });

    test('500 retried for read-only tools', () async {
      final c = mk(err500);
      final r = await c.whoami();
      expect(r.isError, isFalse);
    });

    test('500 retried for send_message, which gets a client_message_id',
        () async {
      final tok = uniqueToken();
      final c = mk(err500, token: tok, model: 'Test Model');
      final r = await c.sendMessage(conversationId: 'c1', text: 'hello');
      expect((r.data as Map)['text'], contains('Test Model'));
      final sent = (await err500.rpcLog())
          .where((e) => jsonEncode(e).contains('client_message_id'))
          .toList();
      expect(sent, isNotEmpty);
    });

    test('500 is NOT retried for a non-idempotent tool without a message id',
        () async {
      final name = toolTraits.entries
          .firstWhere((e) =>
              !e.value.safeToRepeat &&
              !e.value.hasClientMessageId &&
              !e.value.hasModelName)
          .key;
      final c = mk(err500);
      await expectLater(c.callTool(name, <String, dynamic>{}),
          throwsA(isA<McpTransportError>()));
    });
  });

  group('helpers', () {
    test('sendMessage signs with default model and dedupes by id', () async {
      final c = mk(json, model: 'Claude Test');
      final a = await c.sendMessage(
          conversationId: 'c1', text: 'hi', clientMessageId: 'abc-1');
      final b = await c.sendMessage(
          conversationId: 'c1', text: 'hi', clientMessageId: 'abc-1');
      expect((a.data as Map)['message_id'], (b.data as Map)['message_id']);
      expect((b.data as Map)['deduplicated'], isTrue);
      expect((a.data as Map)['text'], endsWith('Claude Test'));
    });

    test('explicit modelName beats the default', () async {
      final c = mk(json, model: 'Default');
      final r = await c.sendMessage(
          conversationId: 'c1', text: 'hi', modelName: 'Explicit');
      expect((r.data as Map)['text'], endsWith('Explicit'));
    });

    test('watchUpdates yields pushed items and acks', () async {
      final tok = uniqueToken();
      final c = mk(json, token: tok);
      await json.push(tok, [
        {'kind': 'mention', 'conversation_id': 'c1', 'text': 'one'},
        {'kind': 'mention', 'conversation_id': 'c1', 'text': 'two'},
      ]);
      final got = <Map<String, dynamic>>[];
      await for (final u in c.watchUpdates(
          waitSeconds: 1, shouldStop: () => got.length == 2)) {
        got.add(u);
      }
      expect(got.map((u) => u['text']), ['one', 'two']);
      // The next page must start after the acked cursor.
      final again = await c.getUpdates(waitSeconds: 0);
      expect((again.data as Map)['updates'], isEmpty);
    });

    test('uploadBytes + sendFile', () async {
      final c = mk(json, model: 'M');
      final id = await c.uploadBytes('c1', 'a.txt', utf8.encode('hello'),
          mime: 'text/plain');
      final r = await c.sendFile(conversationId: 'c1', uploadId: id);
      expect((r.data as Map)['size_bytes'], 5);
    });

    test('notifications stream delivers inbox pushes', () async {
      final tok = uniqueToken();
      final c = mk(json, token: tok);
      await json.push(tok, [
        {'kind': 'mention', 'conversation_id': 'c1', 'text': 'ping'}
      ]);
      final events = await c.notifications().toList();
      expect(events, isNotEmpty);
      expect(events.first['method'], 'notifications/resources/updated');
    });

    test('token-in-path form', () async {
      final c = McpClient(
          token: uniqueToken(),
          baseUrl: json.url,
          tokenInPath: true,
          backoffBase: const Duration(milliseconds: 5));
      expect((await c.whoami()).isError, isFalse);
    });
  });

  group('sse parsing', () {
    test('multi-line data and comments', () {
      expect(parseSseData(': hi\n\ndata: a\ndata: b\n\ndata:c\n\n'),
          ['a\nb', 'c']);
    });
  });
}
