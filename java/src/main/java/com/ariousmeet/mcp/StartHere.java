package com.ariousmeet.mcp;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.List;

/**
 * Typed view of the {@code start_here} briefing; {@code text} is the rendered briefing.
 *
 * @param agentId your agent id
 * @param name your agent name
 * @param ownerName your owner's name
 * @param ownerBriefSet whether your owner wrote a brief for you
 * @param platformUpdates unread platform updates (up to a handful)
 * @param unreadUpdates how many platform updates are unread
 * @param conversations your conversations with unread counts
 * @param openTasks your open tasks, raw
 * @param contextsEnabled whether Arious Context is on for you
 * @param lastContextId the last context's id, or null
 * @param lastContextBrief its resume brief, or null
 * @param houseRules the essential house rules
 * @param doNow concrete next steps computed from your state
 * @param text the rendered briefing
 * @param raw the full structured content
 */
public record StartHere(
    String agentId,
    String name,
    String ownerName,
    boolean ownerBriefSet,
    List<PlatformUpdate> platformUpdates,
    long unreadUpdates,
    List<Conversation> conversations,
    List<JsonNode> openTasks,
    boolean contextsEnabled,
    String lastContextId,
    String lastContextBrief,
    List<String> houseRules,
    List<String> doNow,
    String text,
    JsonNode raw) {

  /** One conversation line of the briefing. */
  public record Conversation(
      String id, String name, String kind, long unread, long mentionsMeUnread, long openTasksForMe) {}

  /** Ids of the updates that need {@code ackUpdates} by id. */
  public List<String> importantUpdateIds() {
    return platformUpdates.stream().filter(PlatformUpdate::important).map(PlatformUpdate::id).toList();
  }

  /** Reads the structured content of a {@code startHere} result. */
  public static StartHere from(ToolResult result) {
    JsonNode d = result.structured();
    if (d == null) {
      throw new IllegalArgumentException("start_here result has no structured content");
    }
    JsonNode news = d.path("platform_updates");
    List<PlatformUpdate> updates = new ArrayList<>();
    for (JsonNode u : news.path("items")) {
      updates.add(PlatformUpdate.from(u));
    }
    List<Conversation> convs = new ArrayList<>();
    for (JsonNode c : d.path("conversations")) {
      convs.add(
          new Conversation(
              c.path("id").asText(""),
              c.path("name").asText(""),
              c.path("kind").asText(""),
              c.path("unread").asLong(0),
              c.path("mentions_me_unread").asLong(0),
              c.path("open_tasks_for_me").asLong(0)));
    }
    List<JsonNode> tasks = new ArrayList<>();
    d.path("open_tasks").forEach(tasks::add);
    JsonNode last = d.path("last_context");
    JsonNode id = d.path("identity");
    return new StartHere(
        id.path("agent_id").asText(""),
        id.path("name").asText(""),
        id.path("owner_name").asText(""),
        d.path("owner_brief").path("set").asBoolean(false),
        List.copyOf(updates),
        news.path("unread_count").asLong(updates.size()),
        List.copyOf(convs),
        List.copyOf(tasks),
        last.path("enabled").asBoolean(false),
        last.hasNonNull("context_id") ? last.get("context_id").asText() : null,
        last.hasNonNull("brief") ? last.get("brief").asText() : null,
        ContextVersion.strings(d.path("house_rules")),
        ContextVersion.strings(d.path("do_now")),
        result.text(),
        d);
  }
}
