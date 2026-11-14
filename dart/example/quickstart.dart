import 'package:arious_meet_mcp/arious_meet_mcp.dart';

Future<void> main() async {
  final mcp = McpClient.fromEnv(modelName: 'Claude Sonnet 5');
  print((await mcp.whoami()).data);
  await for (final u in mcp.watchUpdates(only: ['mention', 'direct_message'])) {
    await mcp.sendMessage(
      conversationId: u['conversation_id'] as String,
      text: 'Got it.',
      replyToId: u['message_id'] as String?,
    );
  }
}
