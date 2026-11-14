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
  public static final class Tool extends McpException {
    private static final long serialVersionUID = 1L;
    private final String tool;

    public Tool(String message, String tool) {
      super(message);
      this.tool = tool;
    }

    public String tool() {
      return tool;
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
