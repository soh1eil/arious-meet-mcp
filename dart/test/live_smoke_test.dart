@Tags(['live'])
library;

import 'dart:io';

import 'package:arious_meet_mcp/arious_meet_mcp.dart';
import 'package:test/test.dart';

/// LIVE smoke test. Calls ONLY the four read-only tools: whoami, get_handbook,
/// search_app_guide, list_organizations. Needs ARIOUS_MCP_TOKEN in the
/// environment; skipped otherwise.
void main() {
  final token = Platform.environment['ARIOUS_MCP_TOKEN'];
  final skip =
      (token == null || token.isEmpty) ? 'ARIOUS_MCP_TOKEN not set' : null;

  test('live read-only tools', () async {
    final c = McpClient.fromEnv();
    await c.initialize();
    final tools = await c.listTools();
    expect(tools, isNotEmpty);
    expect((await c.whoami()).isError, isFalse);
    expect((await c.getHandbook(section: 'formatting')).text, isNotEmpty);
    expect((await c.searchAppGuide(query: 'calls')).isError, isFalse);
    expect((await c.listOrganizations()).isError, isFalse);
    c.close();
  }, skip: skip, tags: 'live');
}
