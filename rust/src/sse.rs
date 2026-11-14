/// Incremental Server-Sent-Events parser: feed text, get complete `data:`
/// payloads (multi-line data joined with `\n`).
#[derive(Debug, Default)]
pub struct SseParser {
    pending: String,
    data: Vec<String>,
}

impl SseParser {
    pub fn new() -> Self {
        Self::default()
    }

    /// Feed a chunk; returns every event completed by it.
    pub fn feed(&mut self, chunk: &str) -> Vec<String> {
        self.pending.push_str(chunk);
        let mut out = Vec::new();
        while let Some(i) = self.pending.find('\n') {
            let mut line: String = self.pending[..i].to_string();
            self.pending.drain(..=i);
            if line.ends_with('\r') {
                line.pop();
            }
            if line.is_empty() {
                if !self.data.is_empty() {
                    out.push(self.data.join("\n"));
                    self.data.clear();
                }
            } else if let Some(v) = line.strip_prefix("data:") {
                self.data.push(v.strip_prefix(' ').unwrap_or(v).to_string());
            }
        }
        out
    }

    /// Flush a final event not followed by a blank line.
    pub fn finish(&mut self) -> Vec<String> {
        let mut out = self.feed("\n");
        out.extend(self.feed("\n"));
        out
    }
}

/// Parse a complete SSE body into its `data:` payloads.
pub fn parse_sse_data(body: &str) -> Vec<String> {
    let mut p = SseParser::new();
    let mut out = p.feed(body);
    out.extend(p.finish());
    out
}
