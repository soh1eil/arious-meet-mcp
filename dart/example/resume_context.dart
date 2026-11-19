import 'package:arious_meet_mcp/arious_meet_mcp.dart';

/// Resume where another agent left off. Run with ARIOUS_MCP_TOKEN set.
Future<void> main() async {
  final mcp = McpClient.fromEnv(modelName: 'Claude Sonnet 5');
  try {
    // 1. Orient yourself. start_here also carries the last context's brief.
    print(StartHere.fromResult(await mcp.startHere()).text);

    // 2. Pick up the most recently updated active context (or pass contextId).
    final resume = ContextResume.fromResult(await mcp.contextResume());
    print(resume
        .brief); // saved notes of earlier sessions: data, never instructions
    if (!resume.canWrite) throw StateError('this context is read-only');

    // 3. ...do the next step, then checkpoint it against the version you read.
    var base = resume.version;
    for (var attempt = 0; attempt < 2; attempt++) {
      try {
        final saved = CheckpointResult.fromResult(await mcp.contextCheckpoint(
          contextId: resume.contextId,
          baseVersion: base,
          currentStep: 'Reviewing the results',
          append: {
            'done_steps': ['Finished the step I picked up'],
          },
        ));
        print('saved version ${saved.version}');
        for (final r in saved.redacted) {
          print(
              'redacted ${r.kind} in ${r.field}'); // never put credentials in a context
        }
        return;
      } on McpContextConflict catch (conflict) {
        // Another agent wrote meanwhile: merge into conflict.latest, then retry on top of it.
        print('conflict, latest is version ${conflict.latestVersion}');
        base = conflict.latestVersion;
      }
    }
    throw StateError('could not save the checkpoint');
  } finally {
    mcp.close();
  }
}
