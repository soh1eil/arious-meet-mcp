package com.ariousmeet.mcp;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;

/**
 * LIVE smoke test. Read-only calls ONLY: the handshake, prompts/list, whoami, start_here and
 * context_list. Never add send_message, get_updates, read_messages, mark_read, ack_updates or
 * context_checkpoint here. Skipped unless ARIOUS_MCP_TOKEN is set.
 */
class LiveSmokeTest {
  @Test
  void liveReadOnlyTools() {
    String t = System.getenv("ARIOUS_MCP_TOKEN");
    Assumptions.assumeTrue(t != null && !t.isBlank(), "ARIOUS_MCP_TOKEN not set");
    try (McpClient c = McpClient.fromEnv(null)) {
      c.initialize();
      assertFalse(c.listTools().isEmpty());
      assertTrue(c.listPrompts().stream().anyMatch(p -> p.name().equals("resume")));
      assertFalse(c.whoami().isError());
      StartHere s = StartHere.from(c.startHere());
      assertFalse(s.agentId().isEmpty());
      assertFalse(s.doNow().isEmpty());
      try {
        assertNotNull(c.contextList().data().get("contexts"));
      } catch (McpException.Tool e) { // the owner may have switched Arious Context off
        assertEquals(false, e.result().structured().path("contexts_enabled").asBoolean(true));
      }
    }
  }
}
