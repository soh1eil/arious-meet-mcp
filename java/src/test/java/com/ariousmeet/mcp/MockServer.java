package com.ariousmeet.mcp;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicLong;

/** Starts the shared Python mock (../mock/server.py) on a free port. */
final class MockServer implements AutoCloseable {
  private static final AtomicLong N = new AtomicLong();
  private static final HttpClient HTTP = HttpClient.newHttpClient();

  private final Process proc;
  final String url;
  final String origin;

  private MockServer(Process p, String url) {
    this.proc = p;
    this.url = url;
    this.origin = url.replace("/v1/mcp", "");
  }

  static String uniqueToken() {
    return "test-java-" + System.nanoTime() + "-" + N.incrementAndGet();
  }

  static MockServer start(String mode) throws IOException {
    Path script = Path.of(System.getProperty("user.dir"), "..", "mock", "server.py").normalize();
    Process p =
        new ProcessBuilder(
                "python3", script.toString(), "--port", "0", "--mode", mode, "--fail-count", "2")
            .redirectError(ProcessBuilder.Redirect.DISCARD)
            .start();
    BufferedReader r =
        new BufferedReader(new InputStreamReader(p.getInputStream(), StandardCharsets.UTF_8));
    String line = r.readLine();
    if (line == null || !line.startsWith("LISTENING ")) {
      p.destroy();
      throw new IOException("mock gave no banner");
    }
    Thread drain =
        new Thread(
            () -> {
              try {
                while (r.readLine() != null) {
                  // discard
                }
              } catch (IOException e) {
                // closed
              }
            });
    drain.setDaemon(true);
    drain.start();
    return new MockServer(p, line.substring("LISTENING ".length()).trim());
  }

  McpClient client(String token, String model) {
    return McpClient.builder()
        .token(token)
        .baseUrl(url)
        .modelName(model)
        .backoffBase(Duration.ofMillis(5))
        .timeout(Duration.ofSeconds(15))
        .build();
  }

  McpClient client() {
    return client(uniqueToken(), "Test Model");
  }

  String log() throws Exception {
    return HTTP.send(
            HttpRequest.newBuilder(URI.create(origin + "/__mock/log")).build(),
            HttpResponse.BodyHandlers.ofString())
        .body();
  }

  void control(String path, String json) throws Exception {
    HTTP.send(
        HttpRequest.newBuilder(URI.create(origin + path))
            .POST(HttpRequest.BodyPublishers.ofString(json))
            .build(),
        HttpResponse.BodyHandlers.discarding());
  }

  void push(String token, String itemsJson) throws Exception {
    String body = "{\"token\":\"" + token + "\",\"items\":" + itemsJson + "}";
    HTTP.send(
        HttpRequest.newBuilder(URI.create(origin + "/__mock/push"))
            .POST(HttpRequest.BodyPublishers.ofString(body))
            .build(),
        HttpResponse.BodyHandlers.discarding());
  }

  @Override
  public void close() {
    proc.destroy();
  }
}
