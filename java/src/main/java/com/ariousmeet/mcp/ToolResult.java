package com.ariousmeet.mcp;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.TextNode;
import java.util.List;

/** Decoded result of {@code tools/call}. */
public final class ToolResult {
  private static final ObjectMapper MAPPER = new ObjectMapper();

  private final String text;
  private final List<JsonNode> content;
  private final JsonNode structured;
  private final boolean error;

  ToolResult(String text, List<JsonNode> content, JsonNode structured, boolean error) {
    this.text = text;
    this.content = content;
    this.structured = structured;
    this.error = error;
  }

  /** First text block. */
  public String text() {
    return text;
  }

  /** Every content block as sent by the server. */
  public List<JsonNode> content() {
    return content;
  }

  /** {@code structuredContent}, or null when the tool provides none. */
  public JsonNode structured() {
    return structured;
  }

  /** True when the tool answered {@code isError}. */
  public boolean isError() {
    return error;
  }

  /**
   * The one-line reminder the server adds to {@code get_updates}, {@code read_messages} and {@code
   * get_message} while Arious Context is on for this agent; null otherwise.
   */
  public String contextReminder() {
    if (structured == null) {
      return null;
    }
    String r = structured.path("context_reminder").asText("");
    return r.isEmpty() ? null : r;
  }

  /** The {@code platform_update} items of a {@code get_updates} result. */
  public List<PlatformUpdate> platformUpdates() {
    List<PlatformUpdate> out = new java.util.ArrayList<>();
    if (structured != null) {
      for (JsonNode u : structured.path("updates")) {
        if ("platform_update".equals(u.path("kind").asText())) {
          out.add(PlatformUpdate.from(u));
        }
      }
    }
    return List.copyOf(out);
  }

  /** Structured content if present, else the text parsed as JSON, else the text. */
  public JsonNode data() {
    if (structured != null) {
      return structured;
    }
    try {
      return MAPPER.readTree(text);
    } catch (JsonProcessingException e) {
      return TextNode.valueOf(text);
    }
  }
}
