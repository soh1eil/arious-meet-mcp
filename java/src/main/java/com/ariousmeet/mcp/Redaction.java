package com.ariousmeet.mcp;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.List;

/**
 * One kind of secret the server removed from a checkpoint before saving it.
 *
 * @param field the context field it was found in
 * @param kind the kind of secret, e.g. {@code api_key}
 * @param count how many spans were replaced
 */
public record Redaction(String field, String kind, long count) {
  static List<Redaction> list(JsonNode array) {
    List<Redaction> out = new ArrayList<>();
    for (JsonNode r : array) {
      out.add(new Redaction(r.path("field").asText(""), r.path("kind").asText(""), r.path("count").asLong(0)));
    }
    return List.copyOf(out);
  }
}
