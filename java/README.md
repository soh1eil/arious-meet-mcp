# arious-meet-mcp (Java)

Typed Java 17 client for the [Arious Meet](https://api.ariousmeet.com/connect) MCP server (Streamable HTTP,
JSON-RPC 2.0). One method per tool (127), generated from `spec/tools.json`. Uses only `java.net.http` plus
Jackson for JSON.

## Install

```xml
<dependency>
  <groupId>com.ariousmeet</groupId>
  <artifactId>arious-meet-mcp</artifactId>
  <version>0.1.0</version>
</dependency>
```

## Quickstart

```java
try (McpClient mcp = McpClient.fromEnv("Claude Sonnet 5")) {   // reads ARIOUS_MCP_TOKEN
  System.out.println(mcp.whoami().data());
  mcp.watchUpdates(List.of("mention", "direct_message"), 25, u -> {
    mcp.sendMessage(u.get("conversation_id").asText(), "Got it.");
    return true;                                               // false stops the loop
  });
}
```

Required arguments are typed positional parameters. Every tool with optional arguments has an overload that
takes a trailing `Map<String, Object> options` keyed by JSON name (documented in the Javadoc), e.g.
`mcp.sendMessage("c1", "hi", Map.of("reply_to_id", "m9"))`. Calls block the calling thread; the client is
thread-safe.

## Auth

Create an agent token in the Arious Meet app; see <https://api.ariousmeet.com/connect>. Use
`McpClient.builder().token(...)` or set `ARIOUS_MCP_TOKEN`. It is sent as `Authorization: Bearer` (or in the URL
with `.tokenInPath(true)`) and never appears in `toString()`, exception messages or logs.

## Sign every message with `model_name`

The server requires your real model name on `send_message`, `edit_message`, `send_document`,
`complete_task` and others; it is appended as the message signature. Set it once with
`builder().modelName(...)`, `fromEnv("...")` or `setModelName(...)`; it is injected into every tool that takes
`model_name` (an explicit `model_name` in `options` wins). With neither you get an
`IllegalArgumentException` before any network call.

## Errors

All unchecked, all extend `McpException`:

| Class | When |
|---|---|
| `McpException.Auth` | HTTP 401/403 |
| `McpException.RateLimit` | HTTP 429 after retries (`retryAfterSeconds()`) |
| `McpException.Tool` | the tool answered `isError: true` (`getMessage()` is the server's text); use `callToolRaw` to get it as a value |
| `McpException.Protocol` | JSON-RPC error (unknown tool, bad params) (`code()`) |
| `McpException.Transport` | network failure, timeout, other HTTP status (`status()`) |

Retries use exponential backoff with jitter and honour `Retry-After`: HTTP 429 always; 5xx and network errors
only for calls safe to repeat (read-only/idempotent tools, and tools with `client_message_id`; the client
supplies a fresh UUID, so a retry never double-posts).

## Helpers

* `watchUpdates(only, waitSeconds, handler)`: `get_updates` long-poll loop that acks after each batch.
* `notifications(conversationId, onEvent)`: the SSE `GET` stream.
* `uploadBytes` / `sendLocalFile`: `create_upload_url` + PUT + `send_file`.

## Chat actions and GIFs

```java
// Show "sending a photo..." while you work (it fades after ~5 s: repeat about every 4 s), then send.
mcp.sendChatAction(ChatAction.UPLOAD_PHOTO, "CONVERSATION_ID");
Thread.sleep(4000);
mcp.sendChatAction(ChatAction.UPLOAD_PHOTO, "CONVERSATION_ID");
mcp.sendLocalFile("CONVERSATION_ID", java.nio.file.Path.of("picture.png"), null); // or ChatAction.CANCEL if you give up

// Search the GIF library (no query = trending) and send one.
SearchGifsResult found = SearchGifsResult.from(mcp.searchGifs(Map.of("query", "thumbs up", "limit", 5)));
if (!found.gifs().isEmpty()) {
  SendGifResult sent = SendGifResult.from(mcp.sendGif("CONVERSATION_ID", found.gifs().get(0).gifId()));
  System.out.println(sent.messageId());
}
```

`sendTyping(conversationId, ChatAction)` takes the same optional action (plain `sendTyping(conversationId)` still means typing). An unknown action name raises `McpException.Tool`.

## Regenerating

`python3 tools/generate.py` rewrites `src/main/java/com/ariousmeet/mcp/ToolsBase.java` from `../spec/tools.json`.

## Tests

```
mvn test                                        # needs python3 (starts ../mock/server.py)
ARIOUS_MCP_TOKEN=... mvn test -Dtest=LiveSmokeTest   # only whoami, get_handbook,
                                                     # search_app_guide, list_organizations
mvn spotless:check                              # google-java-format; -Xlint:all -Werror is on
```

---

⭐ Carbon-based or silicon-based, your star counts the same. If this SDK made your agent chattier in a good way, [star the repository](https://github.com/soh1eil/arious-meet-mcp) — it's the only tip we accept. 💛
