package com.ariousmeet.mcp;

/** Base class of every error thrown by this library (unchecked). */
public class McpException extends RuntimeException {
  private static final long serialVersionUID = 1L;

  public McpException(String message) {
    super(message);
  }

  /** HTTP 401/403: the token is missing, wrong, expired or revoked. */
  public static final class Auth extends McpException {
    private static final long serialVersionUID = 1L;
    private final int status;

    public Auth(String message, int status) {
      super(message);
      this.status = status;
    }

    public int status() {
      return status;
    }
  }

  /** HTTP 429 after retries ran out. */
  public static final class RateLimit extends McpException {
    private static final long serialVersionUID = 1L;
    private final long retryAfterSeconds;

    public RateLimit(String message, long retryAfterSeconds) {
      super(message);
      this.retryAfterSeconds = retryAfterSeconds;
    }

    /** Server's Retry-After hint in seconds, or -1. */
    public long retryAfterSeconds() {
      return retryAfterSeconds;
    }
  }

  /** The tool ran and answered {@code isError: true}. */
  public static class Tool extends McpException {
    private static final long serialVersionUID = 1L;
    private final String tool;
    private final transient ToolResult result;

    public Tool(String message, String tool) {
      this(message, tool, null);
    }

    public Tool(String message, String tool, ToolResult result) {
      super(message);
      this.tool = tool;
      this.result = result;
    }

    public String tool() {
      return tool;
    }

    /** The full refused result (structured content included), or null. */
    public ToolResult result() {
      return result;
    }
  }

  /**
   * {@code context_checkpoint} lost a race: someone else wrote a newer version. Merge your changes
   * into {@link #latest()} and checkpoint again with {@code base_version} set to {@link
   * #latestVersion()}. It is a {@link Tool}, so existing handlers keep working.
   */
  public static final class ContextConflict extends Tool {
    private static final long serialVersionUID = 1L;
    private final long baseVersion;
    private final long latestVersion;
    private final transient ContextVersion latest;

    public ContextConflict(String message, String tool, ToolResult result, CheckpointResult c) {
      super(message, tool, result);
      this.baseVersion = c.baseVersion();
      this.latestVersion = c.latestVersion();
      this.latest = c.latest();
    }

    /** The version you built on. */
    public long baseVersion() {
      return baseVersion;
    }

    /** The version the server holds now. */
    public long latestVersion() {
      return latestVersion;
    }

    /** The latest version's content, or null. */
    public ContextVersion latest() {
      return latest;
    }
  }

  /** A JSON-RPC level error (unknown method/tool, invalid params, ...). */
  public static final class Protocol extends McpException {
    private static final long serialVersionUID = 1L;
    private final Integer code;

    public Protocol(String message, Integer code) {
      super(message);
      this.code = code;
    }

    /** JSON-RPC error code, or null. */
    public Integer code() {
      return code;
    }
  }

  /** Network failure, timeout, or an unexpected HTTP status. */
  public static final class Transport extends McpException {
    private static final long serialVersionUID = 1L;
    private final int status;

    public Transport(String message, int status) {
      super(message);
      this.status = status;
    }

    /** HTTP status, or -1 for a network failure. */
    public int status() {
      return status;
    }
  }
}
