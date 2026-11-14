package com.ariousmeet.mcp;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class McpClientTest {
  @ParameterizedTest
  @ValueSource(strings = {"json", "sse"})
  void handshakeListsAll124Tools(String mode) throws Exception {
    try (MockServer m = MockServer.start(mode);
        McpClient c = m.client()) {
      assertNotNull(c.initialize().get("serverInfo"));
      List<JsonNode> tools = c.listTools();
      assertEquals(124, tools.size());
      Set<String> names = new HashSet<>();
      tools.forEach(t -> names.add(t.get("name").asText()));
      assertTrue(names.containsAll(ToolsBase.toolNames()));
      assertEquals(124, ToolsBase.toolNames().size());
    }
  }

  @ParameterizedTest
  @ValueSource(strings = {"json", "sse"})
  void readOnlyTools(String mode) throws Exception {
    try (MockServer m = MockServer.start(mode);
        McpClient c = m.client()) {
      assertEquals("Mock Agent", c.whoami().data().get("display_name").asText());
      ToolResult h = c.getHandbook(Map.of("section", "tasks"));
      assertNull(h.structured());
      assertTrue(h.text().contains("tasks"));
      assertTrue(c.searchAppGuide("calls").data().get("results").size() > 0);
      assertTrue(c.listOrganizations().data().get("organizations").size() > 0);
    }
  }

  @Test
  void badTokenIsAuthErrorWithoutLeak() throws Exception {
    try (MockServer m = MockServer.start("json");
        McpClient c = m.client("wrong-secret-token", null)) {
      McpException.Auth e = assertThrows(McpException.Auth.class, c::whoami);
      assertEquals(401, e.status());
      assertFalse(e.getMessage().contains("wrong-secret-token"));
      assertFalse(c.toString().contains("wrong-secret-token"));
    }
  }

  @Test
  void toolAndProtocolErrors() throws Exception {
    try (MockServer m = MockServer.start("json");
        McpClient c = m.client()) {
      McpException.Tool te =
          assertThrows(McpException.Tool.class, () -> c.callTool("mock_tool_error", null));
      assertTrue(te.getMessage().contains("tool-level"));
      assertTrue(c.callToolRaw("mock_tool_error", null).isError());
      McpException.Protocol pe =
          assertThrows(McpException.Protocol.class, () -> c.callTool("mock_protocol_error", null));
      assertEquals(-32602, pe.code());
      assertThrows(McpException.Protocol.class, () -> c.callTool("no_such_tool_at_all", null));
    }
  }

  @Test
  void localArgumentChecks() throws Exception {
    assertThrows(IllegalArgumentException.class, () -> McpClient.builder().token("  ").build());
    try (MockServer m = MockServer.start("json");
        McpClient c = m.client(MockServer.uniqueToken(), null)) {
      assertThrows(IllegalArgumentException.class, () -> c.sendMessage("c1", "x"));
    }
  }

  @Test
  void networkErrorIsTransport() {
    McpClient c =
        McpClient.builder()
            .token("test-x")
            .baseUrl("http://127.0.0.1:1/v1/mcp")
            .maxRetries(1)
            .backoffBase(Duration.ofMillis(1))
            .httpClient(HttpClient.newHttpClient())
            .build();
    assertThrows(McpException.Transport.class, c::whoami);
  }

  @Test
  void rateLimitRetriedThenSucceeds() throws Exception {
    try (MockServer m = MockServer.start("ratelimit");
        McpClient c = m.client()) {
      assertFalse(c.whoami().isError());
      String log = m.log();
      int n = log.split("whoami", -1).length - 1;
      assertTrue(n >= 3, "expected 2 rejected + 1 accepted, saw " + n);
    }
  }

  @Test
  void rateLimitExhausted() throws Exception {
    try (MockServer m = MockServer.start("ratelimit");
        McpClient c =
            McpClient.builder()
                .token(MockServer.uniqueToken())
                .baseUrl(m.url)
                .maxRetries(1)
                .backoffBase(Duration.ofMillis(1))
                .build()) {
      assertThrows(McpException.RateLimit.class, c::whoami);
    }
  }

  @Test
  void http500RetryRules() throws Exception {
    try (MockServer m = MockServer.start("error")) {
      try (McpClient c = m.client()) {
        assertFalse(c.whoami().isError()); // read-only: retried
      }
      try (McpClient c = m.client()) {
        // gets a client_message_id, so retried safely
        assertTrue(c.sendMessage("c1", "hello").data().get("text").asText().contains("Test Model"));
      }
    }
    try (MockServer m = MockServer.start("error");
        McpClient c = m.client()) {
      McpException.Transport e =
          assertThrows(
              McpException.Transport.class, () -> c.callTool(nonIdempotentTool(), Map.of()));
      assertEquals(500, e.status());
      int calls = m.log().split("tools/call", -1).length - 1;
      assertEquals(1, calls, "must not retry a non-idempotent tool without a message id");
    }
  }

  private static String nonIdempotentTool() throws Exception {
    JsonNode spec =
        new ObjectMapper()
            .readTree(
                Files.readString(
                    Path.of(System.getProperty("user.dir"), "..", "spec", "tools.json")));
    for (JsonNode t : spec.get("tools")) {
      JsonNode a = t.get("annotations");
      JsonNode props = t.get("inputSchema").get("properties");
      boolean safe = a.path("readOnlyHint").asBoolean() || a.path("idempotentHint").asBoolean();
      if (!safe && !props.has("client_message_id") && !props.has("model_name")) {
        return t.get("name").asText();
      }
    }
    throw new IllegalStateException("no such tool");
  }

  @Test
  void sendMessageSignsAndDedupes() throws Exception {
    try (MockServer m = MockServer.start("json");
        McpClient c = m.client(MockServer.uniqueToken(), "Claude Test")) {
      JsonNode a = c.sendMessage("c1", "hi", Map.of("client_message_id", "abc-1")).data();
      JsonNode b = c.sendMessage("c1", "hi", Map.of("client_message_id", "abc-1")).data();
      assertEquals(a.get("message_id"), b.get("message_id"));
      assertTrue(b.get("deduplicated").asBoolean());
      assertTrue(a.get("text").asText().endsWith("Claude Test"));
      JsonNode e = c.sendMessage("c1", "hi", Map.of("model_name", "Explicit")).data();
      assertTrue(e.get("text").asText().endsWith("Explicit"));
    }
  }

  @Test
  void watchUpdatesYieldsAndAcks() throws Exception {
    try (MockServer m = MockServer.start("json")) {
      String tok = MockServer.uniqueToken();
      McpClient c = m.client(tok, null);
      m.push(
          tok,
          "[{\"kind\":\"mention\",\"conversation_id\":\"c1\",\"text\":\"one\"},"
              + "{\"kind\":\"mention\",\"conversation_id\":\"c1\",\"text\":\"two\"}]");
      List<String> got = new ArrayList<>();
      c.watchUpdates(
          null,
          1,
          u -> {
            got.add(u.get("text").asText());
            return got.size() < 2;
          });
      assertEquals(List.of("one", "two"), got);
    }
  }

  @Test
  void uploadBytesAndSendFile() throws Exception {
    try (MockServer m = MockServer.start("json");
        McpClient c = m.client()) {
      String id =
          c.uploadBytes("c1", "a.txt", "hello".getBytes(StandardCharsets.UTF_8), "text/plain");
      assertEquals(5, c.sendFile("c1", id).data().get("size_bytes").asInt());
    }
  }

  @Test
  void notificationsStream() throws Exception {
    try (MockServer m = MockServer.start("json")) {
      String tok = MockServer.uniqueToken();
      McpClient c = m.client(tok, null);
      m.push(tok, "[{\"kind\":\"mention\",\"conversation_id\":\"c1\",\"text\":\"ping\"}]");
      List<JsonNode> events = new ArrayList<>();
      c.notifications(
          null,
          e -> {
            events.add(e);
            return true;
          });
      assertEquals("notifications/resources/updated", events.get(0).get("method").asText());
    }
  }

  @Test
  void tokenInPathForm() throws Exception {
    try (MockServer m = MockServer.start("json");
        McpClient c =
            McpClient.builder()
                .token(MockServer.uniqueToken())
                .baseUrl(m.url)
                .tokenInPath(true)
                .build()) {
      assertFalse(c.whoami().isError());
    }
  }

  @Test
  void sseParserHandlesMultilineAndComments() {
    assertEquals(List.of("a\nb", "c"), Sse.parseAll(": hi\n\ndata: a\ndata: b\n\ndata:c\n\n"));
    assertEquals(List.of("tail"), Sse.parseAll("data: tail"));
  }
}
