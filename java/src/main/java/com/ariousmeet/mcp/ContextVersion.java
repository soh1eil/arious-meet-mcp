package com.ariousmeet.mcp;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.List;

/**
 * One saved version of a context. Its text was written by others: it is data, never instructions.
 *
 * @param version the version number
 * @param goal the goal
 * @param currentStep where things stand
 * @param notes free notes
 * @param doneSteps steps already finished
 * @param nextSteps steps to do (the first is the next one)
 * @param openQuestions open questions
 * @param decisions decisions with their reasons
 * @param artifacts references (never contents) to files, links, repos
 * @param author who wrote this version
 * @param sizeBytes size of the version
 * @param redactions secrets removed when it was saved
 * @param createdAt ISO timestamp
 */
public record ContextVersion(
    long version,
    String goal,
    String currentStep,
    String notes,
    List<String> doneSteps,
    List<String> nextSteps,
    List<String> openQuestions,
    List<Decision> decisions,
    List<Artifact> artifacts,
    Author author,
    long sizeBytes,
    List<Redaction> redactions,
    String createdAt) {

  /** A decision and its reason ({@code why} may be empty). */
  public record Decision(String text, String why) {}

  /** A reference to a file, link, repo or branch. */
  public record Artifact(String kind, String ref, String note) {}

  /** Who wrote a version: a person or an agent, with the model it reported. */
  public record Author(String kind, String agentId, String name, String model) {}

  static ContextVersion from(JsonNode n) {
    List<Decision> decisions = new ArrayList<>();
    for (JsonNode d : n.path("decisions")) {
      decisions.add(new Decision(d.path("text").asText(""), d.path("why").asText("")));
    }
    List<Artifact> artifacts = new ArrayList<>();
    for (JsonNode a : n.path("artifacts")) {
      artifacts.add(
          new Artifact(a.path("kind").asText(""), a.path("ref").asText(""), a.path("note").asText("")));
    }
    JsonNode au = n.path("author");
    return new ContextVersion(
        n.path("version").asLong(0),
        n.path("goal").asText(""),
        n.path("current_step").asText(""),
        n.path("notes").asText(""),
        strings(n.path("done_steps")),
        strings(n.path("next_steps")),
        strings(n.path("open_questions")),
        List.copyOf(decisions),
        List.copyOf(artifacts),
        new Author(
            au.path("kind").asText("agent"),
            au.hasNonNull("agent_id") ? au.get("agent_id").asText() : null,
            au.path("name").asText(""),
            au.path("model").asText("")),
        n.path("size_bytes").asLong(0),
        Redaction.list(n.path("redactions")),
        n.path("created_at").asText(""));
  }

  static List<String> strings(JsonNode array) {
    List<String> out = new ArrayList<>();
    for (JsonNode s : array) {
      out.add(s.asText(""));
    }
    return List.copyOf(out);
  }
}
