import 'package:arious_meet_mcp/arious_meet_mcp.dart';
import 'package:test/test.dart';

import 'mock_server.dart';

void main() {
  late MockServer json, sse;

  setUpAll(() async {
    json = await MockServer.start();
    sse = await MockServer.start(mode: 'sse');
  });
  tearDownAll(() async {
    await Future.wait([json.stop(), sse.stop()]);
  });

  McpClient mk(MockServer s, {String? token, String model = 'Test Model'}) =>
      McpClient(
        token: token ?? uniqueToken(),
        baseUrl: s.url,
        modelName: model,
        backoffBase: const Duration(milliseconds: 5),
        timeout: const Duration(seconds: 10),
      );

  Future<String> create(McpClient c, String title, String goal) async {
    final r = await c.contextCreate(title: title, goal: goal);
    return (r.structured!['context'] as Map)['id'] as String;
  }

  for (final mode in ['json', 'sse']) {
    test('resume where another agent left off ($mode)', () async {
      final s = mode == 'json' ? json : sse;
      final token = uniqueToken();
      final writer = mk(s, token: token, model: 'Agent A');
      final reader = mk(s, token: token, model: 'Agent B');
      final cid = await create(writer, 'Ship 0.3', 'Release the SDK');
      final first = CheckpointResult.fromResult(await writer.contextCheckpoint(
        contextId: cid,
        baseVersion: 1,
        currentStep: 'Writing tests',
        append: {
          'done_steps': ['Spec read'],
          'next_steps': ['Run the suite'],
        },
      ));
      expect(first.version, 2);
      expect(first.conflict, isFalse);
      expect(first.wasRedacted, isFalse);

      final resume =
          ContextResume.fromResult(await reader.contextResume()); // newest
      expect(resume.contextId, cid);
      expect(resume.version, 2);
      expect(resume.canWrite, isTrue);
      expect(resume.scope, 'personal');
      expect(resume.organizationId, isNull);
      expect(resume.brief, contains('Where we are now: Writing tests'));
      expect(resume.brief, contains('Next step: Run the suite'));
      final next = CheckpointResult.fromResult(await reader.contextCheckpoint(
        contextId: cid,
        baseVersion: resume.version,
        append: {
          'done_steps': ['Suite green'],
        },
      ));
      expect(next.version, 3);
      final got = (await reader.contextGet(contextId: cid, history: 2)).data
          as Map<String, dynamic>;
      final v = ContextVersion.fromJson(got['version'] as Map<String, dynamic>);
      expect(v.author.model, 'Agent B');
      expect(v.doneSteps, ['Spec read', 'Suite green']);
      expect(
          (got['history'] as List).map((h) => (h as Map)['version']), [3, 2]);
    });
  }

  test('checkpoint redacts secrets and reports them', () async {
    final c = mk(json);
    final cid = await create(c, 'T', 'g');
    final res = CheckpointResult.fromResult(await c.contextCheckpoint(
      contextId: cid,
      baseVersion: 1,
      notes: 'use sk-abcdefghijklmnopqrstuvwxyz and password=hunter2 here',
    ));
    expect(res.wasRedacted, isTrue);
    expect(
        res.redacted,
        unorderedEquals([
          const Redaction(field: 'notes', kind: 'api_key', count: 1),
          const Redaction(field: 'notes', kind: 'secret_value', count: 1),
        ]));
    final notes = (((await c.contextGet(contextId: cid)).structured!['version']
        as Map)['notes']) as String;
    expect(notes, isNot(contains('hunter2')));
    expect(notes, contains('[REDACTED:api_key]'));
  });

  test('a lost race throws McpContextConflict carrying the latest', () async {
    final token = uniqueToken();
    final c = mk(json, token: token);
    final cid = await create(c, 'T', 'g');
    await json.control('/__mock/context_write', {
      'token': token,
      'context_id': cid,
      'current_step': 'elsewhere',
      'model': 'Other',
    });
    await expectLater(
      c.contextCheckpoint(contextId: cid, baseVersion: 1, currentStep: 'mine'),
      throwsA(isA<McpContextConflict>()
          .having((e) => e.baseVersion, 'baseVersion', 1)
          .having((e) => e.latestVersion, 'latestVersion', 2)
          .having((e) => e.latest?.currentStep, 'latest', 'elsewhere')
          .having((e) => e.latest?.author.model, 'model', 'Other')
          .having((e) => e.tool, 'tool', 'context_checkpoint')),
    );
    try {
      await c.contextCheckpoint(contextId: cid, baseVersion: 1);
      fail('must throw');
    } on McpToolError catch (e) {
      expect(e, isA<McpContextConflict>()); // old handlers keep working
    }
    final ok = CheckpointResult.fromResult(await c.contextCheckpoint(
        contextId: cid, baseVersion: 2, currentStep: 'mine'));
    expect(ok.version, 3);
  });

  test('conflict as a result with throwOnError: false', () async {
    final token = uniqueToken();
    final c = mk(json, token: token);
    final cid = await create(c, 'T', 'g');
    await json
        .control('/__mock/context_write', {'token': token, 'context_id': cid});
    final raw = await c.callTool('context_checkpoint',
        {'context_id': cid, 'base_version': 1, 'notes': 'x'}, false);
    expect(raw.isError, isTrue);
    final res = CheckpointResult.fromResult(raw);
    expect(res.conflict, isTrue);
    expect(res.baseVersion, 1);
    expect(res.latestVersion, 2);
    expect(res.latest?.version, 2);
  });

  test('other tool errors stay plain McpToolError', () async {
    final c = mk(json);
    await expectLater(
        c.contextGet(contextId: 'nope'),
        throwsA(isA<McpToolError>()
            .having((e) => e is McpContextConflict, 'conflict', isFalse)
            .having((e) => e.message, 'message', contains('not found'))));
    await expectLater(
        c.contextResume(),
        throwsA(isA<McpToolError>().having(
            (e) => e.message, 'message', contains('no active context'))));
  });

  test('list, search, status and validation', () async {
    final c = mk(json);
    final a = await create(c, 'Alpha plan', 'first goal');
    final b = await create(c, 'Beta plan', 'second goal');
    List<String> ids(ToolResult r) => [
          for (final x in r.structured!['contexts'] as List)
            (x as Map)['id'] as String,
        ];
    expect(ids(await c.contextList()), unorderedEquals([a, b]));
    await c.contextSetStatus(contextId: a, status: 'paused');
    expect(ids(await c.contextList(status: 'paused')), [a]);
    expect(ids(await c.contextSearch(query: 'second')), [b]);
    expect(() => c.contextCheckpoint(contextId: a, baseVersion: -1),
        throwsA(isA<McpToolError>()));
    expect(() => c.contextSetStatus(contextId: a, status: 'archived'),
        throwsA(isA<McpToolError>()));
  });

  test('context off is a tool error with the reason', () async {
    final token = uniqueToken();
    final c = mk(json, token: token);
    await json.control('/__mock/contexts', {'token': token, 'enabled': false});
    await expectLater(
        c.contextList(),
        throwsA(isA<McpToolError>().having(
            (e) => e.result?['structuredContent'],
            'structured',
            {'contexts_enabled': false, 'reason': 'turned_off_by_owner'})));
    expect(StartHere.fromResult(await c.startHere()).contextsEnabled, isFalse);
    await json.control('/__mock/contexts', {'token': token, 'enabled': true});
    expect((await c.contextList()).structured!['contexts'], isEmpty);
  });

  test('organization scope and classification', () async {
    final c = mk(json);
    final personal = await create(c, 'Mine', 'g');
    final org = (await c.contextCreate(
            title: 'Board pack',
            goal: 'g',
            organizationId: 'org-1',
            classification: 'confidential'))
        .structured!;
    final oc = org['context'] as Map;
    expect(oc['scope'], 'organization');
    expect(oc['classification'], 'confidential');
    final mine = (await c.contextList()).structured!['contexts'] as List;
    expect(mine.map((x) => (x as Map)['id']), [personal]);
    final listed = (await c.contextList(organizationId: 'org-1')).structured!;
    expect(listed['scope'], 'organization');
    expect((listed['contexts'] as List).single['id'], oc['id']);
    final res = ContextResume.fromResult(await c.contextResume(
        contextId: oc['id'] as String,
        organizationId: 'org-1',
        conversationId: 'conv-1'));
    expect(res.scope, 'organization');
    expect(res.organizationId, 'org-1');
    expect(res.classification, 'confidential');
    await expectLater(
        c.contextCreate(
            title: 'S', organizationId: 'org-1', classification: 'secret'),
        throwsA(isA<McpToolError>()
            .having((e) => e.message, 'message', contains('clearance'))));
    await expectLater(
        c.contextList(organizationId: 'org-9'),
        throwsA(isA<McpToolError>().having(
            (e) => e.message, 'message', contains('organization not found'))));
  });

  test('startHere is typed and platform updates are acked by id', () async {
    final c = mk(json);
    final cid = await create(c, 'Resume me', 'goal');
    final s = StartHere.fromResult(await c.startHere());
    expect(s.name, 'Mock Agent');
    expect(s.contextsEnabled, isTrue);
    expect(s.lastContextId, cid);
    expect(s.lastContextBrief, contains('Resume me'));
    expect(s.unreadUpdates, 2);
    expect(s.importantUpdateIds, ['upd-context']);
    expect(s.conversations.single['id'], 'conv-1');
    expect(s.houseRules, isNotEmpty);
    expect(s.doNow, isNotEmpty);
    expect(s.text, startsWith('START HERE'));
    await c.ackUpdates(updateIds: s.importantUpdateIds);
    expect(
        StartHere.fromResult(await c.startHere()).importantUpdateIds, isEmpty);
    expect(() => c.ackUpdates(), throwsA(isA<McpToolError>()));
  });

  test('prompts: list and get', () async {
    final c = mk(json);
    final prompts = await c.listPrompts();
    expect(prompts.map((p) => p.name), ['start', 'resume']);
    expect(prompts[0].arguments, isEmpty);
    expect(prompts[1].arguments.map((a) => (a.name, a.required)),
        [('context_id', false), ('organization_id', false)]);
    final cid = await create(c, 'Prompted', 'g');
    final res = await c.getPrompt('resume', {'context_id': cid});
    expect(res.messages.single.role, 'user');
    expect(res.text, contains('Title: Prompted'));
    expect((await c.getPrompt('start')).text, contains('START HERE'));
    await expectLater(c.getPrompt('nope'),
        throwsA(isA<McpProtocolError>().having((e) => e.code, 'code', -32602)));
  });

  test('contextReminder and platform_update items', () async {
    final token = uniqueToken();
    final c = mk(json, token: token);
    await json.push(token, [
      {
        'kind': 'message',
        'conversation_id': 'c1',
        'message_id': 'm1',
        'text': 'hi',
      },
      {
        'kind': 'platform_update',
        'id': 'upd-x',
        'title': 'New',
        'importance': 'important',
      },
    ]);
    final res = await c.getUpdates();
    expect(res.contextReminder, contains('context_checkpoint'));
    expect(
        res.platformUpdates.map((u) => (u.id, u.important)), [('upd-x', true)]);
    expect((await c.readMessages(conversationId: 'c1')).contextReminder,
        isNotNull);
    expect(
        (await c.getMessage(conversationId: 'c1', messageId: 'm1'))
            .contextReminder,
        isNotNull);
    expect((await c.readMessages(conversationId: 'empty')).contextReminder,
        isNull);
    await json.control('/__mock/contexts', {'token': token, 'enabled': false});
    expect((await c.getUpdates()).contextReminder, isNull);
  });
}
