export interface ToolResult<T = any> {
  /** Concatenated text content blocks. */
  text: string;
  /** structuredContent if the server sent one. */
  structured: Record<string, any> | null;
  /** Raw content blocks. */
  content: Array<Record<string, any>>;
  isError: boolean;
  /** structured if present, else the text parsed as JSON, else the text. */
  data: T;
}

export interface ClientOptions {
  /** Agent token. Defaults to env ARIOUS_MCP_TOKEN (Node/Deno/Bun). Not needed with a /v1/mcp/t/<token> URL. */
  token?: string;
  /** Default https://api.ariousmeet.com/v1/mcp */
  url?: string;
  /** Your real model name; filled into every tool that needs it. */
  modelName?: string;
  /** Per-request timeout in ms. Default 60000. */
  timeoutMs?: number;
  /** Retries on 429/5xx/network errors. Default 3. */
  maxRetries?: number;
  /** Base backoff in ms. Default 500. */
  backoffMs?: number;
  /** Throw ToolError when the server sets isError (default true). */
  throwOnToolError?: boolean;
  /** Custom fetch (tests, proxies). */
  fetch?: typeof fetch;
}
