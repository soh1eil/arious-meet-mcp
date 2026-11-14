/** Base class of every error this SDK throws. */
export class AriousError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
  }
}
export class ConfigError extends AriousError {}
/** HTTP 401/403. Never retried. */
export class AuthError extends AriousError {
  constructor(
    message: string,
    public readonly status = 401,
  ) {
    super(message);
  }
}
/** HTTP 429 that survived all retries. retryAfter is in seconds. */
export class RateLimitError extends AriousError {
  constructor(
    message: string,
    public readonly retryAfter: number | null = null,
  ) {
    super(message);
  }
}
/** HTTP 5xx or another unexpected status that survived all retries. */
export class ServerError extends AriousError {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}
/** Network failure or timeout that survived all retries. */
export class TransportError extends AriousError {}
/** JSON-RPC error object or unparseable reply. */
export class ProtocolError extends AriousError {
  constructor(
    message: string,
    public readonly code: number | null = null,
  ) {
    super(message);
  }
}
/** The tool ran and refused (isError: true). message is the server's text. */
export class ToolError extends AriousError {
  constructor(
    message: string,
    public readonly result: unknown = null,
  ) {
    super(message);
  }
}
