import {
  AriousError,
  AuthError,
  ConfigError,
  ContextConflict,
  ProtocolError,
  RateLimitError,
  ServerError,
  ToolError,
  TransportError,
} from "./errors.js";
import { GeneratedTools, TOOL_META } from "./generated.js";
import {
  type CheckpointConflict,
  type ClientOptions,
  type Prompt,
  type PromptResult,
  type ToolResult,
  isCheckpointConflict,
} from "./types.js";

export const DEFAULT_URL = "https://api.ariousmeet.com/v1/mcp";
const PROTOCOL_VERSION = "2025-06-18";
const SDK = "arious-meet-mcp-ts/0.3.0";

type Json = any;

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason);
    const t = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        reject(signal.reason);
      },
      { once: true },
    );
  });

/** Pick the JSON-RPC message answering `id` out of a JSON or SSE body. */
export function parseBody(contentType: string, text: string, id: unknown): Json {
  if (contentType.includes("text/event-stream")) {
    for (const block of text.replace(/\r\n/g, "\n").split("\n\n")) {
      const data = block
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).replace(/^ /, ""))
        .join("\n");
      if (!data.trim()) continue;
      let m: Json;
      try {
        m = JSON.parse(data);
      } catch {
        continue;
      }
      if (m && m.id === id && ("result" in m || "error" in m)) return m;
    }
    throw new ProtocolError(`SSE stream ended without a reply to request ${String(id)}`);
  }
  let m: Json;
  try {
    m = JSON.parse(text);
  } catch (e) {
    throw new ProtocolError(`reply is not valid JSON: ${(e as Error).message}`);
  }
  if (m === null || typeof m !== "object") throw new ProtocolError("reply is not a JSON-RPC object");
  return m;
}

function httpError(status: number, text: string, retryAfter: number | null): AriousError {
  let detail = text.trim().slice(0, 300);
  try {
    const b = JSON.parse(text);
    if (b && typeof b === "object" && b.error) detail = String(b.error);
  } catch {
    /* keep raw text */
  }
  if (status === 401 || status === 403) return new AuthError(`HTTP ${status}: ${detail}`, status);
  if (status === 429) return new RateLimitError(`HTTP 429: ${detail}`, retryAfter);
  return new ServerError(`HTTP ${status}: ${detail}`, status);
}

function toToolResult(raw: Json): ToolResult {
  if (raw === null || typeof raw !== "object") throw new ProtocolError("tools/call result is not an object");
  const content: Array<Record<string, any>> = Array.isArray(raw.content)
    ? raw.content.filter((c: Json) => c && typeof c === "object")
    : [];
  const text = content
    .filter((c) => c.type === "text")
    .map((c) => String(c.text ?? ""))
    .join("\n");
  const structured = raw.structuredContent && typeof raw.structuredContent === "object" ? raw.structuredContent : null;
  let data: Json = structured;
  if (data === null) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  const reminder = structured?.context_reminder;
  const contextReminder = typeof reminder === "string" && reminder ? reminder : null;
  return { text, structured, content, isError: !!raw.isError, contextReminder, data };
}

function uuid(): string {
  return globalThis.crypto.randomUUID();
}

/** MCP client for Arious Meet. Uses only fetch, so it runs on Node 18+, Deno and Bun. */
export class AriousClient extends GeneratedTools {
  readonly url: string;
  /** Real model name used to sign messages; may be changed at any time. */
  modelName?: string;
  serverInfo: Record<string, any> = {};
  private readonly token: string;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly backoffMs: number;
  private readonly throwOnToolError: boolean;
  private readonly fetchImpl: typeof fetch;
  private sessionId: string | null = null;
  private initPromise: Promise<void> | null = null;
  private nextId = 0;

  constructor(opts: ClientOptions = {}) {
    super();
    this.url = opts.url ?? DEFAULT_URL;
    const env = (globalThis as any).process?.env ?? (globalThis as any).Deno?.env?.toObject?.() ?? {};
    this.token = opts.token ?? env.ARIOUS_MCP_TOKEN ?? "";
    if (!this.token && !this.url.includes("/mcp/t/")) {
      throw new ConfigError("no token: pass { token } or set ARIOUS_MCP_TOKEN (or use a /v1/mcp/t/<token> URL)");
    }
    this.modelName = opts.modelName;
    this.timeoutMs = opts.timeoutMs ?? 60_000;
    this.maxRetries = opts.maxRetries ?? 3;
    this.backoffMs = opts.backoffMs ?? 500;
    this.throwOnToolError = opts.throwOnToolError ?? true;
    this.fetchImpl = opts.fetch ?? ((...a) => globalThis.fetch(...a));
  }

  private redact(s: string): string {
    let out = s;
    if (this.token) out = out.split(this.token).join("***");
    const tail = this.url.replace(/\/+$/, "").split("/").pop() ?? "";
    if (this.url.includes("/mcp/t/") && tail.length > 8) out = out.split(tail).join("***");
    return out;
  }

  private headers(): Record<string, string> {
    const h: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json, text/event-stream",
      "MCP-Protocol-Version": PROTOCOL_VERSION,
      "X-Arious-SDK": SDK,
    };
    if (this.token) h.Authorization = `Bearer ${this.token}`;
    if (this.sessionId) h["Mcp-Session-Id"] = this.sessionId;
    return h;
  }

  private delay(attempt: number, retryAfter: number | null): number {
    if (retryAfter !== null) return Math.min(retryAfter * 1000, 60_000);
    const base = Math.min(this.backoffMs * 2 ** attempt, 20_000);
    return base * (0.5 + Math.random() / 2);
  }

  /** Retry rule: a 429 means the call never ran. After 5xx/network only idempotent calls are safe. */
  private canRetry(name: string | null, args: Record<string, unknown>, status: number | null): boolean {
    if (name === null || status === 429) return true;
    const m = TOOL_META[name];
    if (!m) return false;
    return m.readOnly || m.idempotent || !!args.client_message_id;
  }

  private async post(
    payload: Record<string, unknown>,
    retryOk: (status: number | null) => boolean,
    signal?: AbortSignal,
  ): Promise<Json> {
    let attempt = 0;
    for (;;) {
      let status: number | null = null;
      let retryAfter: number | null = null;
      let failure: AriousError;
      try {
        const sigs = [AbortSignal.timeout(this.timeoutMs)];
        if (signal) sigs.push(signal);
        const resp = await this.fetchImpl(this.url, {
          method: "POST",
          headers: this.headers(),
          body: JSON.stringify(payload),
          signal: sigs.length > 1 ? AbortSignal.any(sigs) : sigs[0],
        });
        status = resp.status;
        const ra = resp.headers.get("Retry-After");
        retryAfter = ra !== null && ra !== "" && !Number.isNaN(Number(ra)) ? Math.max(0, Number(ra)) : null;
        const text = await resp.text();
        if (status < 400) {
          const sid = resp.headers.get("Mcp-Session-Id");
          if (sid && payload.method === "initialize") this.sessionId = sid;
          if (status === 202 || text === "") return null;
          return parseBody(resp.headers.get("Content-Type") ?? "", text, payload.id);
        }
        failure = httpError(status, text, retryAfter);
      } catch (e) {
        if (e instanceof AriousError) throw e;
        if (signal?.aborted) throw e;
        failure = new TransportError(`${(e as Error).name}: ${this.redact((e as Error).message)}`);
      }
      const retryable = status === null || status === 429 || status >= 500;
      if (failure instanceof AuthError || !retryable || attempt >= this.maxRetries || !retryOk(status)) throw failure;
      await sleep(this.delay(attempt, retryAfter), signal);
      attempt++;
    }
  }

  private async rpc(
    method: string,
    params?: Record<string, unknown>,
    retryOk: (status: number | null) => boolean = () => true,
    signal?: AbortSignal,
  ): Promise<Json> {
    const payload: Record<string, unknown> = {
      jsonrpc: "2.0",
      id: ++this.nextId,
      method,
    };
    if (params) payload.params = params;
    const msg = await this.post(payload, retryOk, signal);
    if (msg === null) return null;
    if (msg.error) throw new ProtocolError(String(msg.error.message ?? "error"), msg.error.code ?? null);
    return msg.result;
  }

  /** Run the initialize handshake (done automatically on first use). */
  initialize(): Promise<Record<string, any>> {
    return this.doInitialize().then(() => this.serverInfo);
  }

  private async doInitialize(): Promise<void> {
    const result = await this.rpc("initialize", {
      protocolVersion: PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: { name: "arious-meet-mcp-ts", version: "0.2.0" },
    });
    this.serverInfo = result?.serverInfo ?? {};
    await this.post({ jsonrpc: "2.0", method: "notifications/initialized" }, () => true);
  }

  private ensureInitialized(): Promise<void> {
    if (!this.initPromise) {
      this.initPromise = this.doInitialize().catch((e) => {
        this.initPromise = null;
        throw e;
      });
    }
    return this.initPromise;
  }

  async listTools(): Promise<Array<Record<string, any>>> {
    await this.ensureInitialized();
    const r = await this.rpc("tools/list");
    return r?.tools ?? [];
  }

  /** List the MCP prompts the server offers (`start` and `resume`). */
  async listPrompts(): Promise<Prompt[]> {
    await this.ensureInitialized();
    const r = await this.rpc("prompts/list");
    return r?.prompts ?? [];
  }

  /**
   * Fetch a prompt as ready-made messages, e.g. `getPrompt("resume", { context_id })`.
   * A refusal (unknown prompt, contexts off, nothing to resume) is a ProtocolError.
   */
  async getPrompt(name: string, args: Record<string, string> = {}): Promise<PromptResult> {
    await this.ensureInitialized();
    const params: Record<string, unknown> = { name };
    if (Object.keys(args).length) params.arguments = args;
    const r = await this.rpc("prompts/get", params);
    const messages = (Array.isArray(r?.messages) ? r.messages : []).map((m: Json) => ({
      role: String(m?.role ?? "user"),
      text: typeof m?.content === "object" && m.content ? String(m.content.text ?? "") : String(m?.content ?? ""),
    }));
    return {
      description: String(r?.description ?? ""),
      messages,
      text: messages.map((m: { text: string }) => m.text).join("\n"),
    };
  }

  async ping(): Promise<void> {
    await this.ensureInitialized();
    await this.rpc("ping");
  }

  /** Call any tool by name. Throws ToolError if the server sets isError. */
  async callTool(
    name: string,
    args: Record<string, unknown> = {},
    opts: { signal?: AbortSignal } = {},
  ): Promise<ToolResult> {
    const a: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(args)) if (v !== undefined && v !== null) a[k] = v;
    const meta = TOOL_META[name];
    if (meta?.modelName && !a.model_name) {
      if (!this.modelName) {
        throw new ConfigError(
          `${name} needs model_name: pass model_name or set modelName on the client (sign every message with your real model name)`,
        );
      }
      a.model_name = this.modelName;
    }
    if (meta?.clientMessageId && !a.client_message_id) a.client_message_id = uuid();
    await this.ensureInitialized();
    const result = await this.rpc("tools/call", { name, arguments: a }, (s) => this.canRetry(name, a, s), opts.signal);
    const res = toToolResult(result);
    if (res.isError && this.throwOnToolError) {
      if (isCheckpointConflict(res.structured)) {
        throw new ContextConflict(res.text || "context conflict", res.structured as CheckpointConflict, res);
      }
      throw new ToolError(res.text || "tool error", res);
    }
    return res;
  }

  /**
   * Long-poll get_updates forever. Each batch is acknowledged (ack_updates) once the
   * consumer has taken all of it, so a crash replays the batch. Transient errors back
   * off and continue; AuthError/ToolError propagate. Stop with signal or by breaking.
   */
  async *watchUpdates(
    opts: {
      only?: string[];
      waitSeconds?: number;
      ack?: boolean;
      maxTextChars?: number;
      signal?: AbortSignal;
    } = {},
  ): AsyncGenerator<Record<string, any>> {
    const { only, waitSeconds = 25, ack = true, maxTextChars, signal } = opts;
    let cursor: string | undefined;
    let failures = 0;
    while (!signal?.aborted) {
      let res: ToolResult;
      try {
        res = await this.getUpdates({
          cursor,
          wait_seconds: waitSeconds,
          only,
          max_text_chars: maxTextChars,
        });
      } catch (e) {
        if (signal?.aborted) return;
        if (e instanceof RateLimitError || e instanceof ServerError || e instanceof TransportError) {
          failures++;
          try {
            await sleep(this.delay(Math.min(failures, 6), null), signal);
          } catch {
            return;
          }
          continue;
        }
        throw e;
      }
      failures = 0;
      const data = res.data && typeof res.data === "object" ? res.data : {};
      const updates: Array<Record<string, any>> = data.updates ?? [];
      const next: string | undefined = data.next_cursor;
      for (const u of updates) yield u;
      if (next) {
        cursor = next;
        if (ack && updates.length) await this.ackUpdates({ cursor: next });
      }
    }
  }

  /**
   * create_upload_url, PUT the bytes, then send_file. Returns send_file's result
   * (or the create_upload_url ticket with send:false).
   */
  async uploadAndSend(
    conversationId: string,
    file: Uint8Array | ArrayBuffer | Blob,
    opts: {
      filename: string;
      mime?: string;
      caption?: string;
      send?: boolean;
    } & Record<string, unknown>,
  ): Promise<ToolResult> {
    const { filename, mime, caption, send = true, ...sendArgs } = opts;
    const blob = file instanceof Blob ? file : new Blob([file as BlobPart]);
    const contentType = mime ?? (blob.type || "application/octet-stream");
    const ticket = await this.createUploadUrl({
      conversation_id: conversationId,
      filename,
      size: blob.size,
      mime: contentType,
    });
    const info = ticket.data as {
      upload_url: string;
      headers?: Record<string, string>;
      upload_id: string;
    };
    const headers = { "Content-Type": contentType, ...(info.headers ?? {}) };
    let attempt = 0;
    for (;;) {
      let failure: AriousError;
      let status: number | null = null;
      try {
        const resp = await this.fetchImpl(info.upload_url, {
          method: "PUT",
          headers,
          body: blob,
          signal: AbortSignal.timeout(this.timeoutMs),
        });
        status = resp.status;
        if (status < 400) break;
        failure = httpError(status, await resp.text(), null);
      } catch (e) {
        if (e instanceof AriousError) throw e;
        failure = new TransportError(`upload failed: ${(e as Error).name}`);
      }
      const retryable = status === null || status >= 500 || status === 429;
      if (failure instanceof AuthError || !retryable || attempt >= this.maxRetries) throw failure;
      await sleep(this.delay(attempt, null));
      attempt++;
    }
    if (!send) return ticket;
    return this.sendFile({
      conversation_id: conversationId,
      upload_id: info.upload_id,
      caption,
      ...sendArgs,
    } as any);
  }

  /** Node-only convenience: read a file from disk and uploadAndSend it. */
  async uploadAndSendPath(
    conversationId: string,
    path: string,
    opts: {
      filename?: string;
      mime?: string;
      caption?: string;
      send?: boolean;
    } & Record<string, unknown> = {},
  ): Promise<ToolResult> {
    const { readFile } = await import("node:fs/promises");
    const { basename } = await import("node:path");
    const bytes = await readFile(path);
    return this.uploadAndSend(conversationId, new Uint8Array(bytes), {
      ...opts,
      filename: opts.filename ?? basename(path),
    });
  }
}
