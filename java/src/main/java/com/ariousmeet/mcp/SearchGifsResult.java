package com.ariousmeet.mcp;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.List;

/**
 * Typed view of a {@code search_gifs} result.
 *
 * @param gifs the matches
 * @param busy true when the live GIF source was busy and the list may be shorter than usual
 */
public record SearchGifsResult(List<Gif> gifs, boolean busy) {
  /** Reads the structured content of a {@code searchGifs} result. */
  public static SearchGifsResult from(ToolResult result) {
    JsonNode data = result.structured();
    if (data == null) {
      throw new IllegalArgumentException("search_gifs result has no structured content");
    }
    List<Gif> gifs = new ArrayList<>();
    for (JsonNode g : data.path("gifs")) {
      gifs.add(
          new Gif(
              g.path("gif_id").asText(""),
              g.path("title").asText(""),
              g.path("width").asLong(0),
              g.path("height").asLong(0),
              g.path("content_type").asText(""),
              g.path("source").asText(""),
              g.hasNonNull("preview_url") ? g.get("preview_url").asText() : null));
    }
    return new SearchGifsResult(List.copyOf(gifs), data.path("busy").asBoolean(false));
  }
}
