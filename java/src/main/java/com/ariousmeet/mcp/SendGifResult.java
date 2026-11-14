package com.ariousmeet.mcp;

import com.fasterxml.jackson.databind.JsonNode;

/** Typed view of a {@code send_gif} result. {@code sentViaGrantName} is null unless sent via a grant. */
public record SendGifResult(
    String messageId,
    String conversationId,
    String attachmentId,
    String gifId,
    String sentViaGrantName) {
  /** Reads the structured content of a {@code sendGif} result. */
  public static SendGifResult from(ToolResult result) {
    JsonNode d = result.structured();
    if (d == null) {
      throw new IllegalArgumentException("send_gif result has no structured content");
    }
    return new SendGifResult(
        d.path("message_id").asText(""),
        d.path("conversation_id").asText(""),
        d.path("attachment_id").asText(""),
        d.path("gif_id").asText(""),
        d.hasNonNull("sent_via_grant_name") ? d.get("sent_via_grant_name").asText() : null);
  }
}
