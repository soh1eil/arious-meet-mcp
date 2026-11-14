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
