package com.ariousmeet.mcp;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;

/**
 * Typed view of a {@code context_checkpoint} result. On success {@code version} is the new version
 * and {@code redacted} lists every secret the server removed. A lost race is {@link
 * McpException.ContextConflict} by default; with {@code callToolRaw} (or {@code contextCheckpoint}
 * results handed back raw) {@link #from} gives {@code conflict() == true} with {@code
 * latestVersion} and {@code latest} filled in.
 *
 * @param version the new version (0 on conflict)
 * @param sizeBytes size of the saved version
 * @param redacted secrets removed before saving
 * @param conflict true when the checkpoint was refused because someone else wrote meanwhile
 * @param baseVersion on conflict, the version you built on
 * @param latestVersion on conflict, the version the server holds now
 * @param latest on conflict, the latest version's content, else null
 */
public record CheckpointResult(
    long version,
    long sizeBytes,
    List<Redaction> redacted,
    boolean conflict,
    long baseVersion,
    long latestVersion,
    ContextVersion latest) {
  /** Reads the structured content of a {@code contextCheckpoint} result. */
  public static CheckpointResult from(ToolResult result) {
    JsonNode d = result.structured();
    if (d == null) {
      throw new IllegalArgumentException("context_checkpoint result has no structured content");
    }
    if (d.path("conflict").asBoolean(false)) {
      return new CheckpointResult(
          0,
          0,
          List.of(),
          true,
          d.path("base_version").asLong(0),
          d.path("latest_version").asLong(0),
          d.hasNonNull("latest") ? ContextVersion.from(d.get("latest")) : null);
    }
    return new CheckpointResult(
        d.path("version").asLong(0),
        d.path("size_bytes").asLong(0),
        Redaction.list(d.path("redacted")),
        false,
        0,
        0,
        null);
  }

  /** True when the server removed at least one secret. */
  public boolean wasRedacted() {
    return !redacted.isEmpty();
  }
}
