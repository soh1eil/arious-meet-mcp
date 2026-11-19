@Tags(['live'])
library;

import 'dart:io';

import 'package:arious_meet_mcp/arious_meet_mcp.dart';
import 'package:test/test.dart';

/// LIVE smoke test. Read-only calls ONLY: the handshake, prompts/list, whoami,
/// start_here and context_list. Never add sendMessage, getUpdates,
/// readMessages, markRead, ackUpdates or contextCheckpoint here. Needs
/// ARIOUS_MCP_TOKEN in the environment; skipped otherwise.
void main() {
  final token = Platform.environment['ARIOUS_MCP_TOKEN'];
  final skip =
      (token == null || token.isEmpty) ? 'ARIOUS_MCP_TOKEN not set' : null;

  test('live read-only tools', () async {
    final c = McpClient.fromEnv();
    await c.initialize();
    expect(await c.listTools(), isNotEmpty);
    expect((await c.listPrompts()).map((p) => p.name),
        containsAll(['start', 'resume']));
    expect((await c.whoami()).isError, isFalse);
    final start = StartHere.fromResult(await c.startHere());
    expect(start.agentId, isNotEmpty);
    expect(start.doNow, isNotEmpty);
    try {
      expect((await c.contextList()).structured!['contexts'], isA<List>());
    } on McpToolError catch (e) {
      // the owner may have switched Arious Context off
      expect(e.result?['structuredContent']?['contexts_enabled'], isFalse);
    }
    c.close();
  }, skip: skip, tags: 'live');
}
