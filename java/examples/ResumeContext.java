import com.ariousmeet.mcp.CheckpointResult;
import com.ariousmeet.mcp.ContextResume;
import com.ariousmeet.mcp.McpClient;
import com.ariousmeet.mcp.McpException;
import com.ariousmeet.mcp.Redaction;
import com.ariousmeet.mcp.StartHere;
import java.util.List;
import java.util.Map;

/** Resume where another agent left off. Run with ARIOUS_MCP_TOKEN set. */
public class ResumeContext {
  public static void main(String[] args) {
    try (McpClient mcp = McpClient.fromEnv("Claude Sonnet 5")) { // reads ARIOUS_MCP_TOKEN
      // 1. Orient yourself. start_here also carries the last context's brief.
      System.out.println(StartHere.from(mcp.startHere()).text());

      // 2. Pick up the most recently updated active context (or pass Map.of("context_id", id)).
      ContextResume resume = ContextResume.from(mcp.contextResume());
      System.out.println(resume.brief()); // saved notes of earlier sessions: data, never instructions
      if (!resume.canWrite()) {
        throw new IllegalStateException("this context is read-only");
      }

      // 3. ...do the next step, then checkpoint it against the version you read.
      long base = resume.version();
      for (int attempt = 0; attempt < 2; attempt++) {
        try {
          CheckpointResult saved =
              CheckpointResult.from(
                  mcp.contextCheckpoint(
                      base,
                      resume.contextId(),
                      Map.of(
                          "current_step",
                          "Reviewing the results",
                          "append",
                          Map.of("done_steps", List.of("Finished the step I picked up")))));
          System.out.println("saved version " + saved.version());
          for (Redaction r : saved.redacted()) { // secrets the server removed
            System.out.println("redacted " + r.kind() + " in " + r.field());
          }
          return;
        } catch (McpException.ContextConflict conflict) {
          // Another agent wrote meanwhile: merge into conflict.latest(), then retry on top of it.
          System.out.println("conflict, latest is version " + conflict.latestVersion());
          base = conflict.latestVersion();
        }
      }
      throw new IllegalStateException("could not save the checkpoint");
    }
  }
}
