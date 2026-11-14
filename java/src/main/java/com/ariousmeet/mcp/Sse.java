package com.ariousmeet.mcp;

import java.util.ArrayList;
import java.util.List;

/** Incremental Server-Sent-Events parser. */
public final class Sse {
  private final StringBuilder pending = new StringBuilder();
  private final List<String> data = new ArrayList<>();

  /** Feed a chunk of text; returns every {@code data:} payload it completed. */
  public List<String> feed(String chunk) {
    pending.append(chunk);
    String all = pending.toString();
    List<String> out = new ArrayList<>();
    int start = 0;
    int i;
    while ((i = all.indexOf('\n', start)) >= 0) {
      String line = all.substring(start, i);
      start = i + 1;
      if (line.endsWith("\r")) {
        line = line.substring(0, line.length() - 1);
      }
      if (line.isEmpty()) {
        if (!data.isEmpty()) {
          out.add(String.join("\n", data));
          data.clear();
        }
      } else if (line.startsWith("data:")) {
        String v = line.substring(5);
        data.add(v.startsWith(" ") ? v.substring(1) : v);
      }
    }
    pending.setLength(0);
    pending.append(all.substring(start));
    return out;
  }

  /** Flush a trailing event that had no closing blank line. */
  public List<String> finish() {
    List<String> out = new ArrayList<>(feed("\n"));
    out.addAll(feed("\n"));
    return out;
  }

  /** Parse a complete SSE body into its data payloads. */
  public static List<String> parseAll(String body) {
    Sse p = new Sse();
    List<String> out = new ArrayList<>(p.feed(body));
    out.addAll(p.finish());
    return out;
  }
}
