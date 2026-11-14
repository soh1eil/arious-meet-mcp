package com.ariousmeet.mcp;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Map;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;

/**
 * LIVE smoke test. Calls ONLY whoami, get_handbook, search_app_guide and list_organizations.
 * Skipped unless ARIOUS_MCP_TOKEN is set.
 */
class LiveSmokeTest {
  @Test
  void liveReadOnlyTools() {
    String t = System.getenv("ARIOUS_MCP_TOKEN");
    Assumptions.assumeTrue(t != null && !t.isBlank(), "ARIOUS_MCP_TOKEN not set");
    try (McpClient c = McpClient.fromEnv(null)) {
      c.initialize();
      assertFalse(c.listTools().isEmpty());
      assertFalse(c.whoami().isError());
      assertFalse(c.getHandbook(Map.of("section", "formatting")).text().isEmpty());
      assertFalse(c.searchAppGuide("calls").isError());
      assertTrue(c.listOrganizations().data() != null);
    }
  }
}
