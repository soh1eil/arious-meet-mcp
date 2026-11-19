/// Typed Dart client for the Arious Meet MCP server.
///
/// ```dart
/// final mcp = McpClient.fromEnv(modelName: 'Claude Sonnet 5');
/// print((await mcp.whoami()).data);
/// ```
library;

export 'src/chat_action.dart';
export 'src/client.dart';
export 'src/context.dart';
export 'src/errors.dart';
export 'src/helpers.dart';
export 'src/sse.dart' show parseSseData;
export 'src/tools.g.dart';
