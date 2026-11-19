package com.ariousmeet.mcp;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;

/**
 * Result of {@code prompts/get}: ready-made messages.
 *
 * @param description what the prompt loaded
 * @param messages the messages
 */
public record PromptResult(String description, List<Message> messages) {

  /** One message of a prompt. */
  public record Message(String role, String text) {}

  /** The text of every message, joined by newlines. */
  public String text() {
    return messages.stream().map(Message::text).collect(Collectors.joining("\n"));
  }

  static PromptResult from(JsonNode n) {
    List<Message> msgs = new ArrayList<>();
    for (JsonNode m : n.path("messages")) {
      JsonNode c = m.path("content");
      msgs.add(new Message(m.path("role").asText("user"), c.isObject() ? c.path("text").asText("") : c.asText("")));
    }
    return new PromptResult(n.path("description").asText(""), List.copyOf(msgs));
  }
}
