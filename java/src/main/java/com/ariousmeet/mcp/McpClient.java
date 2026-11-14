package com.ariousmeet.mcp;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Predicate;

/**
 * Arious Meet MCP client with one generated method per tool (inherited from {@link ToolsBase}).
 *
 * <p>Never prints the token. Retries HTTP 429 always, and 5xx / network failures only for calls
 * that are safe to repeat (read-only or idempotent tools, or calls carrying a {@code
 * client_message_id}, which this client fills in when the tool accepts one).
 *
 * <p>Methods block the calling thread. The client is thread-safe.
 */
public final class McpClient extends ToolsBase implements AutoCloseable {
  public static final String DEFAULT_BASE_URL = "https://api.ariousmeet.com/v1/mcp";
  public static final String PROTOCOL_VERSION = "2025-06-18";
  private static final String SDK_VERSION = "0.1.0";
  static final ObjectMapper JSON = new ObjectMapper();

  private final String token;
  private final String baseUrl;
  private final boolean tokenInPath;
  private final Duration timeout;
  private final int maxRetries;
  private final Duration backoffBase;
  private final HttpClient http;
  private final AtomicLong ids = new AtomicLong();
  private final Object initLock = new Object();
  private volatile String modelName;
  private volatile String sessionId;
  private volatile JsonNode initResult;

  private McpClient(Builder b) {
    String t = b.token == null ? "" : b.token.trim();
    if (t.isEmpty()) {
      throw new IllegalArgumentException("token must not be empty");
    }
    this.token = t;
    this.baseUrl = b.baseUrl;
    this.modelName = b.modelName;
    this.tokenInPath = b.tokenInPath;
    this.timeout = b.timeout;
    this.maxRetries = b.maxRetries;
    this.backoffBase = b.backoffBase;
    this.http =
        b.httpClient != null
            ? b.httpClient
            : HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(15)).build();
  }

  /** Builder for {@link McpClient}. */
  public static final class Builder {
    private String token;
    private String baseUrl = DEFAULT_BASE_URL;
    private String modelName;
    private boolean tokenInPath;
    private Duration timeout = Duration.ofSeconds(60);
    private int maxRetries = 3;
    private Duration backoffBase = Duration.ofMillis(500);
    private HttpClient httpClient;

    public Builder token(String v) {
      this.token = v;
      return this;
    }

    public Builder baseUrl(String v) {
      this.baseUrl = v;
      return this;
    }

    /** Default {@code model_name} for every tool that takes one. */
    public Builder modelName(String v) {
      this.modelName = v;
      return this;
    }

    /** Use the {@code /t/{token}} URL form instead of the Authorization header. */
    public Builder tokenInPath(boolean v) {
      this.tokenInPath = v;
      return this;
    }

    public Builder timeout(Duration v) {
      this.timeout = v;
      return this;
    }

    public Builder maxRetries(int v) {
      this.maxRetries = v;
      return this;
    }

    public Builder backoffBase(Duration v) {
      this.backoffBase = v;
      return this;
    }

    public Builder httpClient(HttpClient v) {
      this.httpClient = v;
      return this;
    }

    public McpClient build() {
      return new McpClient(this);
    }
  }

  public static Builder builder() {
    return new Builder();
  }

  /** Reads {@code ARIOUS_MCP_TOKEN} (and optional {@code ARIOUS_MCP_URL}). */
  public static McpClient fromEnv(String modelName) {
    String t = System.getenv("ARIOUS_MCP_TOKEN");
    if (t == null || t.isBlank()) {
      throw new McpException.Auth("ARIOUS_MCP_TOKEN is not set", 0);
    }
    Builder b = builder().token(t).modelName(modelName);
    String u = System.getenv("ARIOUS_MCP_URL");
    if (u != null && !u.isEmpty()) {
      b.baseUrl(u);
    }
    return b.build();
  }

  /** Changes the default {@code model_name}. */
  public void setModelName(String name) {
    this.modelName = name;
  }

  @Override
  public String toString() {
    return "McpClient(" + baseUrl + ")";
  }

  @Override
  public void close() {
    // java.net.http.HttpClient has no close() on Java 17; nothing to release.
  }

  private URI url() {
    if (tokenInPath) {
      return URI.create(baseUrl.replaceAll("/+$", "") + "/t/" + token + "/");
    }
    return URI.create(baseUrl);
  }

  private HttpRequest.Builder request(URI uri, boolean sse) {
    HttpRequest.Builder b =
        HttpRequest.newBuilder(uri)
            .header("Accept", sse ? "text/event-stream" : "application/json, text/event-stream")
            .header("User-Agent", "arious-meet-mcp-java/" + SDK_VERSION)
            .header("MCP-Protocol-Version", PROTOCOL_VERSION);
    if (!tokenInPath) {
      b.header("Authorization", "Bearer " + token);
    }
    String sid = sessionId;
    if (sid != null) {
      b.header("Mcp-Session-Id", sid);
    }
    return b;
  }

  /** The {@code initialize} handshake (once; later calls return the cached answer). */
  public JsonNode initialize() {
    JsonNode r = initResult;
    if (r != null) {
      return r;
    }
    synchronized (initLock) {
      if (initResult != null) {
        return initResult;
      }
      ObjectNode params = JSON.createObjectNode();
      params.put("protocolVersion", PROTOCOL_VERSION);
      params.putObject("capabilities");
      params
          .putObject("clientInfo")
          .put("name", "arious-meet-mcp-java")
          .put("version", SDK_VERSION);
      JsonNode res = rpc("initialize", params, true);
      notifyInitialized();
      initResult = res;
      return res;
    }
  }

  /** {@code tools/list}. */
  public List<JsonNode> listTools() {
    initialize();
    JsonNode r = rpc("tools/list", JSON.createObjectNode(), true);
    List<JsonNode> out = new ArrayList<>();
    JsonNode tools = r.get("tools");
    if (tools != null && tools.isArray()) {
      tools.forEach(out::add);
    }
    return out;
  }

  /** {@code ping}. */
  public void ping() {
    initialize();
    rpc("ping", JSON.createObjectNode(), true);
  }

  /** {@code tools/call}; throws {@link McpException.Tool} when the tool answers isError. */
  @Override
  public ToolResult callTool(String name, Map<String, Object> arguments) {
    ToolResult r = callToolRaw(name, arguments);
    if (r.isError()) {
      throw new McpException.Tool(r.text(), name);
    }
    return r;
  }

  /** Like {@link #callTool} but hands back isError results instead of throwing. */
  public ToolResult callToolRaw(String name, Map<String, Object> arguments) {
    initialize();
    Map<String, Object> args = new LinkedHashMap<>();
    if (arguments != null) {
      arguments.forEach(
          (k, v) -> {
            if (v != null) {
              args.put(k, v);
            }
          });
    }
    boolean safe = false;
    ToolsBase.Traits t = ToolsBase.traits(name);
    if (t != null) {
      safe = t.safeToRepeat();
      if (t.hasModelName() && !args.containsKey("model_name") && modelName != null) {
        args.put("model_name", modelName);
      }
      if (t.requiresModelName() && !args.containsKey("model_name")) {
        throw new IllegalArgumentException(
            "model_name is required by " + name + ": pass it or set McpClient modelName");
      }
      if (t.hasClientMessageId() && !args.containsKey("client_message_id")) {
        args.put("client_message_id", UUID.randomUUID().toString());
      }
    }
    if (args.containsKey("client_message_id")) {
      safe = true;
    }
    ObjectNode params = JSON.createObjectNode();
    params.put("name", name);
    params.set("arguments", JSON.valueToTree(args));
    JsonNode res = rpc("tools/call", params, safe);
    List<JsonNode> content = new ArrayList<>();
    String text = "";
    JsonNode c = res.get("content");
    if (c != null && c.isArray()) {
      for (JsonNode b : c) {
        content.add(b);
        if (text.isEmpty() && "text".equals(b.path("type").asText()) && b.hasNonNull("text")) {
          text = b.get("text").asText();
        }
      }
    }
    JsonNode sc = res.get("structuredContent");
    return new ToolResult(
        text,
        content,
        sc != null && sc.isObject() ? sc : null,
        res.path("isError").asBoolean(false));
  }

  /**
   * Opens the server-to-client SSE stream and calls {@code onEvent} with each JSON-RPC notification
   * until it returns false or the server closes the stream.
   *
   * @param conversationId restrict to one conversation, or null
   */
  public void notifications(String conversationId, Predicate<JsonNode> onEvent) {
    initialize();
    URI uri = url();
    if (conversationId != null) {
      String sep = uri.getRawQuery() == null ? "?" : "&";
      uri =
          URI.create(
              uri
                  + sep
                  + "conversation_id="
                  + URLEncoder.encode(conversationId, StandardCharsets.UTF_8));
    }
    HttpRequest req = request(uri, true).GET().build();
    try {
      HttpResponse<InputStream> resp = http.send(req, HttpResponse.BodyHandlers.ofInputStream());
      try (InputStream in = resp.body()) {
        if (resp.statusCode() >= 300) {
          throw statusError(
              resp.statusCode(),
              new String(in.readNBytes(2000), StandardCharsets.UTF_8),
              resp.headers().firstValue("retry-after").orElse(null));
        }
        Sse parser = new Sse();
        try (BufferedReader r =
            new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8))) {
          String line;
          while ((line = r.readLine()) != null) {
            for (String data : parser.feed(line + "\n")) {
              JsonNode node = parseOrNull(data);
              if (node != null && node.isObject() && !onEvent.test(node)) {
                return;
              }
            }
          }
        }
      }
    } catch (IOException e) {
      throw new McpException.Transport("network error: " + e.getClass().getSimpleName(), -1);
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new McpException.Transport("interrupted", -1);
    }
  }

  /**
   * Long-polls {@code get_updates} and calls {@code handler} for every update; it returns true to
   * keep going, false to stop. The cursor is acknowledged ({@code ack_updates}) after a whole batch
   * has been handled, so a crash mid-batch re-delivers instead of losing items. Rate limits and
   * transient failures back off and continue; authentication errors propagate. Stops when the
   * thread is interrupted.
   *
   * @param only update kinds to hear about (mention, direct_message, ...) or null for everything
   * @param waitSeconds long-poll seconds, 0 to 25
   */
  public void watchUpdates(List<String> only, int waitSeconds, Predicate<JsonNode> handler) {
    String cursor = null;
    int failures = 0;
    while (!Thread.currentThread().isInterrupted()) {
      Map<String, Object> opts = new LinkedHashMap<>();
      opts.put("wait_seconds", waitSeconds);
      if (only != null) {
        opts.put("only", only);
      }
      if (cursor != null) {
        opts.put("cursor", cursor);
      }
      ToolResult r;
      try {
        r = getUpdates(opts);
        failures = 0;
      } catch (McpException.RateLimit e) {
        if (!sleep(
            e.retryAfterSeconds() >= 0
                ? Duration.ofSeconds(e.retryAfterSeconds())
                : Duration.ofSeconds(2))) {
          return;
        }
        continue;
      } catch (McpException.Transport e) {
        failures++;
        if (!sleep(Duration.ofSeconds(2L * Math.min(failures, 5)))) {
          return;
        }
        continue;
      }
      JsonNode data = r.data();
      JsonNode updates = data.path("updates");
      String next = data.path("next_cursor").asText("");
      int n = 0;
      if (updates.isArray()) {
        for (JsonNode u : updates) {
          n++;
          if (!handler.test(u)) {
            return;
          }
        }
      }
      if (!next.isEmpty()) {
        if (n > 0) {
          ackUpdates(next);
        }
        cursor = next;
      }
    }
  }

  /**
   * Stages {@code bytes} with {@code create_upload_url}, PUTs them, and returns the {@code
   * upload_id} (for {@code send_message} attachment_ids or {@code send_file}).
   */
  public String uploadBytes(String conversationId, String filename, byte[] bytes, String mime) {
    Map<String, Object> o = new LinkedHashMap<>();
    if (mime != null) {
      o.put("mime", mime);
    }
    ToolResult t = createUploadUrl(conversationId, filename, bytes.length, o);
    JsonNode d = t.data();
    String url = d.path("upload_url").asText(null);
    String id = d.path("upload_id").asText(null);
    if (url == null || id == null) {
      throw new McpException.Protocol("create_upload_url returned no upload_url/upload_id", null);
    }
    Map<String, String> headers = new LinkedHashMap<>();
    d.path("headers")
        .fields()
        .forEachRemaining(e -> headers.put(e.getKey(), e.getValue().asText()));
    putBytes(url, bytes, headers);
    return id;
  }

  /** Uploads a local file and sends it as its own message. */
  public ToolResult sendLocalFile(String conversationId, java.nio.file.Path path, String caption) {
    try {
      byte[] bytes = java.nio.file.Files.readAllBytes(path);
      String id = uploadBytes(conversationId, path.getFileName().toString(), bytes, null);
      Map<String, Object> o = new LinkedHashMap<>();
      if (caption != null) {
        o.put("caption", caption);
      }
      return sendFile(conversationId, id, o);
    } catch (IOException e) {
      throw new McpException("cannot read file: " + e.getMessage());
    }
  }

  /**
   * PUTs raw bytes to an absolute URL. Upload tickets carry their own credential, so no bearer
   * header is sent.
   */
  public void putBytes(String url, byte[] bytes, Map<String, String> headers) {
    int attempt = 0;
    while (true) {
      HttpRequest.Builder b =
          HttpRequest.newBuilder(URI.create(url))
              .timeout(timeout.multipliedBy(5))
              .PUT(HttpRequest.BodyPublishers.ofByteArray(bytes));
      headers.forEach(
          (k, v) -> {
            if (!k.equalsIgnoreCase("content-length") && !k.equalsIgnoreCase("host")) {
              b.header(k, v);
            }
          });
      try {
        HttpResponse<String> resp = http.send(b.build(), HttpResponse.BodyHandlers.ofString());
        int s = resp.statusCode();
        if (s < 300) {
          return;
        }
        if (!(s == 429 || s >= 500) || attempt >= maxRetries) {
          throw statusError(s, resp.body(), resp.headers().firstValue("retry-after").orElse(null));
        }
      } catch (IOException e) {
        if (attempt >= maxRetries) {
          throw new McpException.Transport("upload failed: " + e.getClass().getSimpleName(), -1);
        }
      } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
        throw new McpException.Transport("interrupted", -1);
      }
      if (!sleep(delay(attempt, null))) {
        throw new McpException.Transport("interrupted", -1);
      }
      attempt++;
    }
  }

  // ------------------------------------------------------------ internals

  private void notifyInitialized() {
    ObjectNode body = JSON.createObjectNode();
    body.put("jsonrpc", "2.0").put("method", "notifications/initialized");
    HttpResponse<String> resp = send(body, true);
    if (resp.statusCode() >= 400) {
      throw statusError(
          resp.statusCode(), resp.body(), resp.headers().firstValue("retry-after").orElse(null));
    }
  }

  private JsonNode rpc(String method, JsonNode params, boolean retry) {
    long id = ids.incrementAndGet();
    ObjectNode body = JSON.createObjectNode();
    body.put("jsonrpc", "2.0").put("id", id).put("method", method);
    body.set("params", params);
    HttpResponse<String> resp = send(body, retry);
    int status = resp.statusCode();
    if (status >= 400) {
      throw statusError(status, resp.body(), resp.headers().firstValue("retry-after").orElse(null));
    }
    if ("initialize".equals(method)) {
      resp.headers()
          .firstValue("mcp-session-id")
          .filter(s -> !s.isEmpty())
          .ifPresent(s -> sessionId = s);
    }
    String ct =
        resp.headers().firstValue("content-type").orElse("").toLowerCase(java.util.Locale.ROOT);
    List<JsonNode> msgs = new ArrayList<>();
    if (ct.contains("text/event-stream")) {
      for (String s : Sse.parseAll(resp.body())) {
        JsonNode n = parseOrNull(s);
        if (n != null) {
          msgs.add(n);
        }
      }
    } else {
      JsonNode n = parseOrNull(resp.body());
      if (n == null) {
        throw new McpException.Transport(
            "server returned a non-JSON body (HTTP " + status + ")", status);
      }
      if (n.isArray()) {
        n.forEach(msgs::add);
      } else {
        msgs.add(n);
      }
    }
    JsonNode chosen = null;
    for (JsonNode m : msgs) {
      if (m.has("result") || m.has("error")) {
        if (m.path("id").asLong(-1) == id) {
          chosen = m;
          break;
        }
        if (chosen == null) {
          chosen = m;
        }
      }
    }
    if (chosen == null) {
      throw new McpException.Protocol("no JSON-RPC response in server reply", null);
    }
    JsonNode err = chosen.get("error");
    if (err != null && err.isObject()) {
      throw new McpException.Protocol(
          err.path("message").asText("protocol error"),
          err.has("code") ? Integer.valueOf(err.get("code").asInt()) : null);
    }
    JsonNode result = chosen.get("result");
    if (result == null || !result.isObject()) {
      throw new McpException.Protocol("response has neither result nor error", null);
    }
    return result;
  }

  private HttpResponse<String> send(JsonNode body, boolean retry) {
    String payload = body.toString();
    int attempt = 0;
    while (true) {
      HttpResponse<String> resp = null;
      String netErr = null;
      try {
        HttpRequest req =
            request(url(), false)
                .timeout(timeout)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(payload))
                .build();
        resp = http.send(req, HttpResponse.BodyHandlers.ofString());
      } catch (HttpTimeoutException e) {
        netErr = "request timed out after " + timeout.toSeconds() + "s";
      } catch (IOException e) {
        netErr = "network error: " + e.getClass().getSimpleName();
      } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
        throw new McpException.Transport("interrupted", -1);
      }
      if (resp != null) {
        int s = resp.statusCode();
        boolean retryable = s == 429 || (retry && s >= 500 && s != 501);
        if (!retryable || attempt >= maxRetries) {
          return resp;
        }
        Duration hint =
            resp.headers().firstValue("retry-after").map(McpClient::parseSeconds).orElse(null);
        if (!sleep(delay(attempt, hint))) {
          throw new McpException.Transport("interrupted", -1);
        }
      } else {
        if (!retry || attempt >= maxRetries) {
          throw new McpException.Transport(netErr, -1);
        }
        if (!sleep(delay(attempt, null))) {
          throw new McpException.Transport("interrupted", -1);
        }
      }
      attempt++;
    }
  }

  private Duration delay(int attempt, Duration hint) {
    if (hint != null) {
      return hint.compareTo(Duration.ofSeconds(30)) > 0 ? Duration.ofSeconds(30) : hint;
    }
    long ms = backoffBase.toMillis() * (1L << Math.min(attempt, 10));
    long jitter = ThreadLocalRandom.current().nextLong(Math.max(1, ms / 4));
    return Duration.ofMillis(Math.min(ms + jitter, 20_000));
  }

  private static boolean sleep(Duration d) {
    try {
      Thread.sleep(d.toMillis());
      return true;
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      return false;
    }
  }

  private static Duration parseSeconds(String v) {
    try {
      return Duration.ofSeconds(Long.parseLong(v.trim()));
    } catch (NumberFormatException e) {
      return null;
    }
  }

  private static JsonNode parseOrNull(String s) {
    try {
      return JSON.readTree(s);
    } catch (IOException e) {
      return null;
    }
  }

  private static McpException statusError(int status, String body, String retryAfter) {
    String detail = body == null ? "" : body.substring(0, Math.min(300, body.length()));
    JsonNode j = body == null ? null : parseOrNull(body);
    if (j != null && j.isObject()) {
      JsonNode e = j.has("error") ? j.get("error") : j.get("message");
      if (e != null && e.isTextual()) {
        detail = e.asText();
      } else if (e != null && e.isObject() && e.path("message").isTextual()) {
        detail = e.get("message").asText();
      }
    }
    if (status == 401 || status == 403) {
      return new McpException.Auth(
          "authentication failed (HTTP " + status + "): " + detail, status);
    }
    if (status == 429) {
      Duration d = retryAfter == null ? null : parseSeconds(retryAfter);
      return new McpException.RateLimit(
          "rate limited (HTTP 429): " + detail, d == null ? -1 : d.toSeconds());
    }
    return new McpException.Transport("HTTP " + status + ": " + detail, status);
  }
}
