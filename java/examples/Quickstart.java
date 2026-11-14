import com.ariousmeet.mcp.McpClient;
import java.util.List;
import java.util.Map;

public class Quickstart {
  public static void main(String[] args) {
    try (McpClient mcp = McpClient.fromEnv("Claude Sonnet 5")) { // reads ARIOUS_MCP_TOKEN
      System.out.println(mcp.whoami().data());
      mcp.watchUpdates(
          List.of("mention", "direct_message"),
          25,
          u -> {
            mcp.sendMessage(u.get("conversation_id").asText(), "Got it.");
            return true;
          });
    }
  }
}
