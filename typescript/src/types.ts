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

/**
 * What the agent is doing, for `sendChatAction` and `sendTyping({ action })`.
 * The notice fades after about 5 seconds: repeat about every 4 seconds while the
 * work goes on. `ChatAction.Cancel` clears it at once.
 */
export const ChatAction = {
  Typing: "typing",
  UploadPhoto: "upload_photo",
  UploadVideo: "upload_video",
  RecordVoice: "record_voice",
  UploadVoice: "upload_voice",
  UploadDocument: "upload_document",
  RecordVideoNote: "record_video_note",
  UploadVideoNote: "upload_video_note",
  ChooseSticker: "choose_sticker",
  FindLocation: "find_location",
  Cancel: "cancel",
} as const;
export type ChatAction = (typeof ChatAction)[keyof typeof ChatAction];

/** One `searchGifs` result. `preview_url` is a link on the server, valid for about an hour. */
export interface Gif {
  gif_id: string;
  title: string;
  width: number;
  height: number;
  content_type: string;
  source: string;
  preview_url?: string;
}

/** Structured result of `searchGifs` (`result.data`). `busy` is true when the live GIF source was busy. */
export interface SearchGifsResult {
  gifs: Gif[];
  busy?: boolean;
}

/** Structured result of `sendGif` (`result.data`). */
export interface SendGifResult {
  message_id: string;
  conversation_id: string;
  attachment_id: string;
  gif_id: string;
  sent_via_grant_name?: string;
}
