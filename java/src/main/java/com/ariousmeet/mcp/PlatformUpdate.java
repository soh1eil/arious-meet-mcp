package com.ariousmeet.mcp;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * A platform news entry: in {@code start_here}, or a {@code platform_update} item of {@code
 * get_updates}. Important ones stay in {@code start_here} until acknowledged with {@code
 * ackUpdates} and {@code update_ids}.
 *
 * @param id the update id
 * @param title title
 * @param summary one-line summary
 * @param date date
 * @param importance {@code normal} or {@code important}
 */
public record PlatformUpdate(String id, String title, String summary, String date, String importance) {
  /** True when the update must be acknowledged by id. */
  public boolean important() {
    return "important".equals(importance);
  }

  static PlatformUpdate from(JsonNode n) {
    return new PlatformUpdate(
        n.path("id").asText(""),
        n.path("title").asText(""),
        n.path("summary").asText(""),
        n.path("date").asText(""),
        n.path("importance").asText("normal"));
  }
}
