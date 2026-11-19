package com.ariousmeet.mcp;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

/** Arious Context, start_here, prompts and platform updates against the shared mock. */
class ContextTest {
  private static String create(McpClient c, String title, String goal) {
    return c.contextCreate(title, Map.of("goal", goal)).data().get("context").get("id").asText();
  }

  @ParameterizedTest
  @ValueSource(strings = {"json", "sse"})
  void resumeWhereAnotherAgentLeftOff(String mode) throws Exception {
    try (MockServer m = MockServer.start(mode)) {
      String token = MockServer.uniqueToken();
      try (McpClient writer = m.client(token, "Agent A");
          McpClient reader = m.client(token, "Agent B")) {
        String cid = create(writer, "Ship 0.3", "Release the SDK");
        CheckpointResult first =
            CheckpointResult.from(
                writer.contextCheckpoint(
                    1,
                    cid,
                    Map.of(
                        "current_step",
                        "Writing tests",
                        "append",
                        Map.of(
                            "done_steps",
                            List.of("Spec read"),
                            "next_steps",
                            List.of("Run the suite")))));
        assertEquals(2, first.version());
        assertFalse(first.conflict());
        assertFalse(first.wasRedacted());

        ContextResume resume = ContextResume.from(reader.contextResume()); // newest active context
        assertEquals(cid, resume.contextId());
        assertEquals(2, resume.version());
        assertTrue(resume.canWrite());
        assertEquals("personal", resume.scope());
        assertNull(resume.organizationId());
        assertTrue(resume.brief().contains("Where we are now: Writing tests"));
        assertTrue(resume.brief().contains("Next step: Run the suite"));
        CheckpointResult next =
            CheckpointResult.from(
                reader.contextCheckpoint(
                    resume.version(),
                    cid,
                    Map.of("append", Map.of("done_steps", List.of("Suite green")))));
        assertEquals(3, next.version());
        JsonNode got = reader.contextGet(cid, Map.of("history", 2)).data();
        assertEquals("Agent B", got.get("version").get("author").get("model").asText());
        assertEquals(2, got.get("version").get("done_steps").size());
        assertEquals(3, got.get("history").get(0).get("version").asInt());
        ContextVersion v = ContextVersion.from(got.get("version"));
        assertEquals(List.of("Spec read", "Suite green"), v.doneSteps());
        assertEquals("Agent B", v.author().model());
      }
    }
  }

  @Test
  void checkpointRedactsSecretsAndReportsThem() throws Exception {
    try (MockServer m = MockServer.start("json");
        McpClient c = m.client()) {
      String cid = create(c, "T", "g");
      CheckpointResult res =
          CheckpointResult.from(
              c.contextCheckpoint(
                  1,
                  cid,
                  Map.of("notes", "use sk-abcdefghijklmnopqrstuvwxyz and password=hunter2 here")));
      assertTrue(res.wasRedacted());
      assertEquals(2, res.redacted().size());
      assertTrue(res.redacted().contains(new Redaction("notes", "api_key", 1)));
      assertTrue(res.redacted().contains(new Redaction("notes", "secret_value", 1)));
      String notes = c.contextGet(cid).data().get("version").get("notes").asText();
      assertFalse(notes.contains("hunter2"));
      assertTrue(notes.contains("[REDACTED:api_key]"));
    }
  }

  @Test
  void lostRaceThrowsContextConflictWithLatest() throws Exception {
    try (MockServer m = MockServer.start("json")) {
      String token = MockServer.uniqueToken();
      try (McpClient c = m.client(token, "Test Model")) {
        String cid = create(c, "T", "g");
        m.control(
            "/__mock/context_write",
            "{\"token\":\""
                + token
                + "\",\"context_id\":\""
                + cid
                + "\",\"current_step\":\"elsewhere\",\"model\":\"Other\"}");
        McpException.ContextConflict e =
            assertThrows(
                McpException.ContextConflict.class,
                () -> c.contextCheckpoint(1, cid, Map.of("current_step", "mine")));
        assertTrue(e instanceof McpException.Tool); // old handlers keep working
        assertEquals("context_checkpoint", e.tool());
        assertEquals(1, e.baseVersion());
        assertEquals(2, e.latestVersion());
        assertNotNull(e.latest());
        assertEquals("elsewhere", e.latest().currentStep());
        assertEquals("Other", e.latest().author().model());
        assertTrue(e.result().isError());
        CheckpointResult ok =
            CheckpointResult.from(
                c.contextCheckpoint(e.latestVersion(), cid, Map.of("current_step", "mine")));
        assertEquals(3, ok.version());
      }
    }
  }

  @Test
  void conflictAsResultWithCallToolRaw() throws Exception {
    try (MockServer m = MockServer.start("json")) {
      String token = MockServer.uniqueToken();
      try (McpClient c = m.client(token, "Test Model")) {
        String cid = create(c, "T", "g");
        m.control(
            "/__mock/context_write",
            "{\"token\":\"" + token + "\",\"context_id\":\"" + cid + "\"}");
        ToolResult raw =
            c.callToolRaw(
                "context_checkpoint", Map.of("context_id", cid, "base_version", 1, "notes", "x"));
        assertTrue(raw.isError());
        CheckpointResult res = CheckpointResult.from(raw);
        assertTrue(res.conflict());
        assertEquals(1, res.baseVersion());
        assertEquals(2, res.latestVersion());
        assertEquals(2, res.latest().version());
      }
    }
  }

  @Test
  void otherToolErrorsStayPlainToolErrors() throws Exception {
    try (MockServer m = MockServer.start("json");
        McpClient c = m.client()) {
      McpException.Tool e = assertThrows(McpException.Tool.class, () -> c.contextGet("nope"));
      assertFalse(e instanceof McpException.ContextConflict);
      assertTrue(e.getMessage().contains("not found"));
      assertTrue(
          assertThrows(McpException.Tool.class, c::contextResume)
              .getMessage()
              .contains("no active context"));
    }
  }

  @Test
  void listSearchStatusAndValidation() throws Exception {
    try (MockServer m = MockServer.start("json");
        McpClient c = m.client()) {
      String a = create(c, "Alpha plan", "first goal");
      String b = create(c, "Beta plan", "second goal");
      assertEquals(2, c.contextList().data().get("contexts").size());
      c.contextSetStatus(a, "paused");
      JsonNode paused = c.contextList(Map.of("status", "paused")).data().get("contexts");
      assertEquals(1, paused.size());
      assertEquals(a, paused.get(0).get("id").asText());
      JsonNode hit = c.contextSearch("second").data().get("contexts");
      assertEquals(b, hit.get(0).get("id").asText());
      assertThrows(McpException.Tool.class, () -> c.contextCheckpoint(-1, a));
      assertThrows(McpException.Tool.class, () -> c.contextSetStatus(a, "archived"));
    }
  }

  @Test
  void contextOffIsAToolErrorWithReason() throws Exception {
    try (MockServer m = MockServer.start("json")) {
      String token = MockServer.uniqueToken();
      try (McpClient c = m.client(token, "Test Model")) {
        m.control("/__mock/contexts", "{\"token\":\"" + token + "\",\"enabled\":false}");
        McpException.Tool e = assertThrows(McpException.Tool.class, c::contextList);
        assertFalse(e.result().structured().get("contexts_enabled").asBoolean(true));
        assertEquals("turned_off_by_owner", e.result().structured().get("reason").asText());
        assertFalse(StartHere.from(c.startHere()).contextsEnabled());
        m.control("/__mock/contexts", "{\"token\":\"" + token + "\",\"enabled\":true}");
        assertEquals(0, c.contextList().data().get("contexts").size());
      }
    }
  }

  @Test
  void organizationScopeAndClassification() throws Exception {
    try (MockServer m = MockServer.start("json");
        McpClient c = m.client()) {
      String personal = create(c, "Mine", "g");
      JsonNode org =
          c.contextCreate(
                  "Board pack",
                  Map.of("goal", "g", "organization_id", "org-1", "classification", "confidential"))
              .data();
      String oid = org.get("context").get("id").asText();
      assertEquals("organization", org.get("context").get("scope").asText());
      assertEquals("confidential", org.get("context").get("classification").asText());
      JsonNode mine = c.contextList().data().get("contexts");
      assertEquals(1, mine.size());
      assertEquals(personal, mine.get(0).get("id").asText());
      JsonNode listed = c.contextList(Map.of("organization_id", "org-1")).data();
      assertEquals("organization", listed.get("scope").asText());
      assertEquals(oid, listed.get("contexts").get(0).get("id").asText());
      ContextResume res =
          ContextResume.from(
              c.contextResume(
                  Map.of(
                      "context_id", oid, "organization_id", "org-1", "conversation_id", "conv-1")));
      assertEquals("organization", res.scope());
      assertEquals("org-1", res.organizationId());
      assertEquals("confidential", res.classification());
      assertTrue(
          assertThrows(
                  McpException.Tool.class,
                  () ->
                      c.contextCreate(
                          "S", Map.of("organization_id", "org-1", "classification", "secret")))
              .getMessage()
              .contains("clearance"));
      assertTrue(
          assertThrows(
                  McpException.Tool.class, () -> c.contextList(Map.of("organization_id", "org-9")))
              .getMessage()
              .contains("organization not found"));
    }
  }

  @Test
  void startHereIsTypedAndPlatformUpdatesAreAckedById() throws Exception {
    try (MockServer m = MockServer.start("json");
        McpClient c = m.client()) {
      String cid = create(c, "Resume me", "goal");
      StartHere s = StartHere.from(c.startHere());
      assertEquals("Mock Agent", s.name());
      assertTrue(s.contextsEnabled());
      assertEquals(cid, s.lastContextId());
      assertTrue(s.lastContextBrief().contains("Resume me"));
      assertEquals(2, s.unreadUpdates());
      assertEquals(List.of("upd-context"), s.importantUpdateIds());
      assertEquals("conv-1", s.conversations().get(0).id());
      assertFalse(s.houseRules().isEmpty());
      assertFalse(s.doNow().isEmpty());
      assertTrue(s.text().startsWith("START HERE"));
      c.ackUpdates(Map.of("update_ids", s.importantUpdateIds()));
      assertTrue(StartHere.from(c.startHere()).importantUpdateIds().isEmpty());
      assertThrows(McpException.Tool.class, c::ackUpdates);
    }
  }

  @Test
  void promptsListAndGet() throws Exception {
    try (MockServer m = MockServer.start("json");
        McpClient c = m.client()) {
      List<Prompt> prompts = c.listPrompts();
      assertEquals(List.of("start", "resume"), prompts.stream().map(Prompt::name).toList());
      Prompt resume = prompts.get(1);
      assertEquals(
          List.of(
              new Prompt.Argument("context_id", "Optional: which context to resume.", false),
              new Prompt.Argument(
                  "organization_id",
                  "Optional: resume an organization's context instead of a personal one.",
                  false)),
          resume.arguments());
      assertTrue(prompts.get(0).arguments().isEmpty());
      String cid = create(c, "Prompted", "g");
      PromptResult res = c.getPrompt("resume", Map.of("context_id", cid));
      assertEquals("user", res.messages().get(0).role());
      assertTrue(res.text().contains("Title: Prompted"));
      assertTrue(c.getPrompt("start", null).text().contains("START HERE"));
      McpException.Protocol e =
          assertThrows(McpException.Protocol.class, () -> c.getPrompt("nope", null));
      assertEquals(-32602, e.code());
    }
  }

  @Test
  void contextReminderAndPlatformUpdateItems() throws Exception {
    try (MockServer m = MockServer.start("json")) {
      String token = MockServer.uniqueToken();
      try (McpClient c = m.client(token, "Test Model")) {
        m.push(
            token,
            "[{\"kind\":\"message\",\"conversation_id\":\"c1\",\"message_id\":\"m1\",\"text\":\"hi\"},"
                + "{\"kind\":\"platform_update\",\"id\":\"upd-x\",\"title\":\"New\","
                + "\"importance\":\"important\"}]");
        ToolResult res = c.getUpdates();
        assertTrue(res.contextReminder().contains("context_checkpoint"));
        List<PlatformUpdate> pu = res.platformUpdates();
        assertEquals(1, pu.size());
        assertEquals("upd-x", pu.get(0).id());
        assertTrue(pu.get(0).important());
        assertNotNull(c.readMessages("c1").contextReminder());
        assertNotNull(c.getMessage("c1", "m1").contextReminder());
        assertNull(c.readMessages("empty").contextReminder());
        m.control("/__mock/contexts", "{\"token\":\"" + token + "\",\"enabled\":false}");
        assertNull(c.getUpdates().contextReminder());
      }
    }
  }
}
