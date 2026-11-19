package com.ariousmeet.mcp;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.List;

/**
 * One entry of {@code prompts/list} (the server offers {@code start} and {@code resume}).
 *
 * @param name the prompt name
 * @param title a human title
 * @param description what it loads
 * @param arguments its arguments (may be empty)
 */
public record Prompt(String name, String title, String description, List<Argument> arguments) {

  /** One argument of a prompt. */
  public record Argument(String name, String description, boolean required) {}

  static Prompt from(JsonNode n) {
    List<Argument> args = new ArrayList<>();
    for (JsonNode a : n.path("arguments")) {
      args.add(
          new Argument(
              a.path("name").asText(""),
              a.path("description").asText(""),
              a.path("required").asBoolean(false)));
    }
    return new Prompt(
        n.path("name").asText(""),
        n.path("title").asText(""),
        n.path("description").asText(""),
        List.copyOf(args));
  }
}
