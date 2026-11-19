use std::sync::Arc;
use std::time::Duration;

use rand::Rng;
use reqwest::header::{HeaderMap, HeaderValue, ACCEPT, AUTHORIZATION, CONTENT_TYPE, USER_AGENT};
use serde_json::{json, Map, Value};
use tokio::sync::OnceCell;

use crate::error::{Error, Result};
use crate::sse::{parse_sse_data, SseParser};
use crate::tools::traits_for;
use crate::types::{PlatformUpdate, Prompt, PromptMessage, PromptResult};

pub const DEFAULT_BASE_URL: &str = "https://api.ariousmeet.com/v1/mcp";
pub const PROTOCOL_VERSION: &str = "2025-06-18";
const SDK_VERSION: &str = env!("CARGO_PKG_VERSION");

/// Schema facts the client needs per tool (generated).
#[derive(Debug, Clone, Copy, Default)]
pub struct ToolTraits {
    pub has_model_name: bool,
    pub requires_model_name: bool,
    pub has_client_message_id: bool,
    pub safe_to_repeat: bool,
}

/// Decoded result of `tools/call`.
#[derive(Debug, Clone)]
pub struct ToolResult {
    /// First text block.
    pub text: String,
    /// Every content block as sent by the server.
    pub content: Vec<Value>,
    /// `structuredContent`, if the tool provides it.
    pub structured: Option<Value>,
    pub is_error: bool,
}

impl ToolResult {
    /// Structured content if present, else the text parsed as JSON, else the text.
    pub fn data(&self) -> Value {
        if let Some(s) = &self.structured {
            return s.clone();
        }
        serde_json::from_str(&self.text).unwrap_or_else(|_| Value::String(self.text.clone()))
    }

    /// The one-line reminder the server adds to `get_updates`, `read_messages` and `get_message`
    /// while Arious Context is on for this agent; `None` otherwise.
    pub fn context_reminder(&self) -> Option<String> {
        self.structured
            .as_ref()?
            .get("context_reminder")?
            .as_str()
            .filter(|s| !s.is_empty())
            .map(str::to_string)
    }

    /// The `platform_update` items of a `get_updates` result.
    pub fn platform_updates(&self) -> Vec<PlatformUpdate> {
        self.structured
            .as_ref()
            .and_then(|s| s.get("updates"))
            .and_then(Value::as_array)
            .map(|a| {
                a.iter()
                    .filter(|u| u["kind"] == "platform_update")
                    .filter_map(|u| serde_json::from_value(u.clone()).ok())
                    .collect()
            })
            .unwrap_or_default()
    }

    /// Deserialize [`ToolResult::data`] into a typed model, for example
    /// [`SearchGifsResult`](crate::SearchGifsResult) or [`SendGifResult`](crate::SendGifResult).
    pub fn decode<T: serde::de::DeserializeOwned>(&self) -> Result<T> {
        serde_json::from_value(self.data())
            .map_err(|e| Error::InvalidArgument(format!("cannot decode tool result: {e}")))
    }
}

/// Builder for [`Client`].
#[derive(Default)]
pub struct ClientBuilder {
    token: Option<String>,
    base_url: Option<String>,
    model_name: Option<String>,
    token_in_path: bool,
    timeout: Option<Duration>,
    max_retries: Option<u32>,
    backoff_base: Option<Duration>,
}

impl ClientBuilder {
    pub fn token(mut self, t: impl Into<String>) -> Self {
        self.token = Some(t.into());
        self
    }
    pub fn base_url(mut self, u: impl Into<String>) -> Self {
        self.base_url = Some(u.into());
        self
    }
    /// Default `model_name` for every tool that takes one.
    pub fn model_name(mut self, m: impl Into<String>) -> Self {
        self.model_name = Some(m.into());
        self
    }
    /// Use the `/t/{token}` URL form instead of the Authorization header.
    pub fn token_in_path(mut self, on: bool) -> Self {
        self.token_in_path = on;
        self
    }
    pub fn timeout(mut self, d: Duration) -> Self {
        self.timeout = Some(d);
        self
    }
    pub fn max_retries(mut self, n: u32) -> Self {
        self.max_retries = Some(n);
        self
    }
    pub fn backoff_base(mut self, d: Duration) -> Self {
        self.backoff_base = Some(d);
        self
    }

    pub fn build(self) -> Result<Client> {
        let token = self
            .token
            .map(|t| t.trim().to_string())
            .filter(|t| !t.is_empty())
            .ok_or_else(|| Error::InvalidArgument("token must not be empty".into()))?;
        let timeout = self.timeout.unwrap_or(Duration::from_secs(60));
        let http = reqwest::Client::builder()
            .timeout(timeout)
            .build()
            .map_err(|e| Error::Transport {
                message: format!("cannot build HTTP client: {e}"),
                status: None,
            })?;
        Ok(Client {
            inner: Arc::new(Inner {
                token,
                base_url: self
                    .base_url
                    .unwrap_or_else(|| DEFAULT_BASE_URL.to_string()),
                model_name: self.model_name,
                token_in_path: self.token_in_path,
                timeout,
                max_retries: self.max_retries.unwrap_or(3),
                backoff_base: self.backoff_base.unwrap_or(Duration::from_millis(500)),
                http,
                id: std::sync::atomic::AtomicU64::new(0),
                session: std::sync::Mutex::new(None),
                init: OnceCell::new(),
            }),
        })
    }
}

struct Inner {
    token: String,
    base_url: String,
    model_name: Option<String>,
    token_in_path: bool,
    timeout: Duration,
    max_retries: u32,
    backoff_base: Duration,
    http: reqwest::Client,
    id: std::sync::atomic::AtomicU64,
    session: std::sync::Mutex<Option<String>>,
    init: OnceCell<Value>,
}

/// Low-level Arious Meet MCP client. Cheap to clone (shared state).
///
/// Never prints the token. Retries 429 always, and 5xx/network failures only
/// for calls that are safe to repeat (read-only/idempotent tools, or calls
/// carrying a `client_message_id`, which this client fills in when the tool
/// accepts one).
#[derive(Clone)]
pub struct Client {
    inner: Arc<Inner>,
}

impl std::fmt::Debug for Client {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Client({})", self.inner.base_url)
    }
}

impl Client {
    pub fn builder() -> ClientBuilder {
        ClientBuilder::default()
    }

    /// Reads `ARIOUS_MCP_TOKEN` (and optional `ARIOUS_MCP_URL`).
    pub fn from_env(model_name: Option<&str>) -> Result<Client> {
        let token = std::env::var("ARIOUS_MCP_TOKEN").unwrap_or_default();
        if token.trim().is_empty() {
            return Err(Error::Auth {
                status: 0,
                message: "ARIOUS_MCP_TOKEN is not set".into(),
            });
        }
        let mut b = Client::builder().token(token);
        if let Ok(u) = std::env::var("ARIOUS_MCP_URL") {
            if !u.is_empty() {
                b = b.base_url(u);
            }
        }
        if let Some(m) = model_name {
            b = b.model_name(m);
        }
        b.build()
    }

    fn url(&self) -> String {
        let i = &self.inner;
        if i.token_in_path {
            format!("{}/t/{}/", i.base_url.trim_end_matches('/'), i.token)
        } else {
            i.base_url.clone()
        }
    }

    fn headers(&self, sse: bool) -> HeaderMap {
        let i = &self.inner;
        let mut h = HeaderMap::new();
        h.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
        h.insert(
            ACCEPT,
            HeaderValue::from_static(if sse {
                "text/event-stream"
            } else {
                "application/json, text/event-stream"
            }),
        );
        h.insert(
            USER_AGENT,
            HeaderValue::from_str(&format!("arious-meet-mcp-rust/{SDK_VERSION}"))
                .unwrap_or_else(|_| HeaderValue::from_static("arious-meet-mcp-rust")),
        );
        h.insert(
            "MCP-Protocol-Version",
            HeaderValue::from_static(PROTOCOL_VERSION),
        );
        if !i.token_in_path {
            if let Ok(mut v) = HeaderValue::from_str(&format!("Bearer {}", i.token)) {
                v.set_sensitive(true);
                h.insert(AUTHORIZATION, v);
            }
        }
        if let Some(s) = i.session.lock().ok().and_then(|g| g.clone()) {
            if let Ok(v) = HeaderValue::from_str(&s) {
                h.insert("Mcp-Session-Id", v);
            }
        }
        h
    }

    /// `initialize` handshake (once; later calls return the cached answer).
    pub async fn initialize(&self) -> Result<Value> {
        let v = self
            .inner
            .init
            .get_or_try_init(|| async {
                let res = self
                    .rpc(
                        "initialize",
                        json!({
                            "protocolVersion": PROTOCOL_VERSION,
                            "capabilities": {},
                            "clientInfo": {"name": "arious-meet-mcp-rust", "version": SDK_VERSION},
                        }),
                        true,
                    )
                    .await?;
                self.notify("notifications/initialized").await?;
                Ok::<Value, Error>(res)
            })
            .await?;
        Ok(v.clone())
    }

    /// `tools/list`.
    pub async fn list_tools(&self) -> Result<Vec<Value>> {
        self.initialize().await?;
        let r = self.rpc("tools/list", json!({}), true).await?;
        Ok(r.get("tools")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default())
    }

    /// `prompts/list`: the MCP prompts the server offers (`start` and `resume`).
    pub async fn list_prompts(&self) -> Result<Vec<Prompt>> {
        self.initialize().await?;
        let r = self.rpc("prompts/list", json!({}), true).await?;
        Ok(r.get("prompts")
            .and_then(Value::as_array)
            .map(|a| {
                a.iter()
                    .filter_map(|p| serde_json::from_value(p.clone()).ok())
                    .collect()
            })
            .unwrap_or_default())
    }

    /// `prompts/get`: a prompt as ready-made messages, for example
    /// `get_prompt("resume", [("context_id", id)])`. A refusal (unknown prompt, contexts off,
    /// nothing to resume) is an [`Error::Protocol`].
    pub async fn get_prompt<K, V, I>(&self, name: &str, arguments: I) -> Result<PromptResult>
    where
        I: IntoIterator<Item = (K, V)>,
        K: Into<String>,
        V: Into<String>,
    {
        self.initialize().await?;
        let args: Map<String, Value> = arguments
            .into_iter()
            .map(|(k, v)| (k.into(), Value::String(v.into())))
            .collect();
        let mut params = json!({"name": name});
        if !args.is_empty() {
            params["arguments"] = Value::Object(args);
        }
        let r = self.rpc("prompts/get", params, true).await?;
        let messages = r
            .get("messages")
            .and_then(Value::as_array)
            .map(|a| {
                a.iter()
                    .map(|m| PromptMessage {
                        role: m["role"].as_str().unwrap_or("user").to_string(),
                        text: m["content"]["text"]
                            .as_str()
                            .or_else(|| m["content"].as_str())
                            .unwrap_or("")
                            .to_string(),
                    })
                    .collect()
            })
            .unwrap_or_default();
        Ok(PromptResult {
            description: r["description"].as_str().unwrap_or("").to_string(),
            messages,
        })
    }

    /// `ping`.
    pub async fn ping(&self) -> Result<()> {
        self.initialize().await?;
        self.rpc("ping", json!({}), true).await.map(|_| ())
    }

    /// `tools/call`. Returns `Err(Error::Tool)` when the tool answers `isError`.
    pub async fn call_tool(&self, name: &str, arguments: Value) -> Result<ToolResult> {
        let r = self.call_tool_raw(name, arguments).await?;
        if r.is_error {
            let result = json!({"content": r.content, "structuredContent": r.structured});
            if let Some(c) = r.structured.as_ref().filter(|s| s["conflict"] == true) {
                return Err(Error::ContextConflict {
                    message: r.text.clone(),
                    base_version: c["base_version"].as_i64().unwrap_or(0),
                    latest_version: c["latest_version"].as_i64().unwrap_or(0),
                    latest: serde_json::from_value(c["latest"].clone())
                        .ok()
                        .map(Box::new),
                    result,
                });
            }
            return Err(Error::Tool {
                tool: name.to_string(),
                message: r.text.clone(),
                result,
            });
        }
        Ok(r)
    }

    /// Like [`Client::call_tool`] but hands back `isError` results instead of failing.
    pub async fn call_tool_raw(&self, name: &str, arguments: Value) -> Result<ToolResult> {
        self.initialize().await?;
        let mut args: Map<String, Value> = match arguments {
            Value::Object(m) => m,
            Value::Null => Map::new(),
            _ => {
                return Err(Error::InvalidArgument(
                    "arguments must be a JSON object".into(),
                ))
            }
        };
        args.retain(|_, v| !v.is_null());
        let mut safe = false;
        if let Some(t) = traits_for(name) {
            safe = t.safe_to_repeat;
            if t.has_model_name && !args.contains_key("model_name") {
                if let Some(m) = &self.inner.model_name {
                    args.insert("model_name".into(), Value::String(m.clone()));
                }
            }
            if t.requires_model_name && !args.contains_key("model_name") {
                return Err(Error::InvalidArgument(format!(
                    "model_name is required by {name}: pass it or set ClientBuilder::model_name"
                )));
            }
            if t.has_client_message_id && !args.contains_key("client_message_id") {
                args.insert(
                    "client_message_id".into(),
                    Value::String(uuid::Uuid::new_v4().to_string()),
                );
            }
        }
        if args.contains_key("client_message_id") {
            safe = true;
        }
        let res = self
            .rpc("tools/call", json!({"name": name, "arguments": args}), safe)
            .await?;
        let content: Vec<Value> = res
            .get("content")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let text = content
            .iter()
            .find(|b| b.get("type").and_then(Value::as_str) == Some("text"))
            .and_then(|b| b.get("text").and_then(Value::as_str))
            .unwrap_or("")
            .to_string();
        Ok(ToolResult {
            text,
            content,
            structured: res
                .get("structuredContent")
                .filter(|v| v.is_object())
                .cloned(),
            is_error: res.get("isError").and_then(Value::as_bool).unwrap_or(false),
        })
    }

    /// Opens the server -> client SSE stream and calls `on_event` with each
    /// JSON-RPC notification until it returns `false` or the server closes
    /// the stream.
    pub async fn notifications<F>(
        &self,
        conversation_id: Option<&str>,
        mut on_event: F,
    ) -> Result<()>
    where
        F: FnMut(Value) -> bool,
    {
        self.initialize().await?;
        let mut url = self.url();
        if let Some(c) = conversation_id {
            url.push_str(if url.contains('?') { "&" } else { "?" });
            url.push_str("conversation_id=");
            url.push_str(
                &c.replace('%', "%25")
                    .replace('&', "%26")
                    .replace(' ', "%20"),
            );
        }
        let mut h = self.headers(true);
        h.remove(CONTENT_TYPE);
        let mut resp = self
            .inner
            .http
            .get(url)
            .headers(h)
            .timeout(Duration::from_secs(24 * 3600))
            .send()
            .await
            .map_err(net_err)?;
        if !resp.status().is_success() {
            return Err(self.status_error(resp).await);
        }
        let mut parser = SseParser::new();
        while let Some(chunk) = resp.chunk().await.map_err(net_err)? {
            for data in parser.feed(&String::from_utf8_lossy(&chunk)) {
                if let Ok(v) = serde_json::from_str::<Value>(&data) {
                    if v.is_object() && !on_event(v) {
                        return Ok(());
                    }
                }
            }
        }
        Ok(())
    }

    /// PUTs raw bytes to an absolute URL (upload tickets carry their own
    /// credential, so no bearer header is sent).
    pub async fn put_bytes(
        &self,
        url: &str,
        bytes: Vec<u8>,
        headers: &[(String, String)],
    ) -> Result<()> {
        let i = &self.inner;
        let mut attempt = 0;
        loop {
            let mut req = i.http.put(url).timeout(i.timeout * 5).body(bytes.clone());
            for (k, v) in headers {
                req = req.header(k, v);
            }
            match req.send().await {
                Ok(resp) if resp.status().is_success() => return Ok(()),
                Ok(resp) => {
                    let s = resp.status().as_u16();
                    if !(s == 429 || s >= 500) || attempt >= i.max_retries {
                        return Err(self.status_error(resp).await);
                    }
                }
                Err(e) => {
                    if attempt >= i.max_retries {
                        return Err(net_err(e));
                    }
                }
            }
            tokio::time::sleep(self.delay(attempt, None)).await;
            attempt += 1;
        }
    }

    // ------------------------------------------------------------ internals

    async fn notify(&self, method: &str) -> Result<()> {
        let resp = self
            .send(&json!({"jsonrpc": "2.0", "method": method}), true)
            .await?;
        if resp.status().as_u16() >= 400 {
            return Err(self.status_error(resp).await);
        }
        Ok(())
    }

    async fn rpc(&self, method: &str, params: Value, retry: bool) -> Result<Value> {
        let id = self
            .inner
            .id
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst)
            + 1;
        let body = json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params});
        let resp = self.send(&body, retry).await?;
        if resp.status().as_u16() >= 400 {
            return Err(self.status_error(resp).await);
        }
        if method == "initialize" {
            if let Some(s) = resp
                .headers()
                .get("mcp-session-id")
                .and_then(|v| v.to_str().ok())
                .filter(|s| !s.is_empty())
            {
                if let Ok(mut g) = self.inner.session.lock() {
                    *g = Some(s.to_string());
                }
            }
        }
        let ct = resp
            .headers()
            .get(CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .to_ascii_lowercase();
        let status = resp.status().as_u16();
        let text = resp.text().await.map_err(net_err)?;
        let msgs: Vec<Value> = if ct.contains("text/event-stream") {
            parse_sse_data(&text)
                .iter()
                .filter_map(|s| serde_json::from_str(s).ok())
                .collect()
        } else {
            match serde_json::from_str::<Value>(&text) {
                Ok(Value::Array(a)) => a,
                Ok(v) => vec![v],
                Err(_) => {
                    return Err(Error::Transport {
                        message: format!("server returned a non-JSON body (HTTP {status})"),
                        status: Some(status),
                    })
                }
            }
        };
        let mut fallback: Option<&Value> = None;
        for m in &msgs {
            if m.get("result").is_some() || m.get("error").is_some() {
                if m.get("id").and_then(Value::as_u64) == Some(id) {
                    fallback = Some(m);
                    break;
                }
                fallback.get_or_insert(m);
            }
        }
        let msg = fallback.ok_or_else(|| Error::Protocol {
            code: None,
            message: "no JSON-RPC response in server reply".into(),
        })?;
        if let Some(e) = msg.get("error").filter(|e| e.is_object()) {
            return Err(Error::Protocol {
                code: e.get("code").and_then(Value::as_i64),
                message: e
                    .get("message")
                    .and_then(Value::as_str)
                    .unwrap_or("protocol error")
                    .to_string(),
            });
        }
        match msg.get("result") {
            Some(r) if r.is_object() => Ok(r.clone()),
            _ => Err(Error::Protocol {
                code: None,
                message: "response has neither result nor error".into(),
            }),
        }
    }

    async fn send(&self, body: &Value, retry: bool) -> Result<reqwest::Response> {
        let i = &self.inner;
        let payload = body.to_string();
        let mut attempt = 0;
        loop {
            let r = i
                .http
                .post(self.url())
                .headers(self.headers(false))
                .body(payload.clone())
                .send()
                .await;
            match r {
                Ok(resp) => {
                    let s = resp.status().as_u16();
                    let retryable = s == 429 || (retry && s >= 500 && s != 501);
                    if !retryable || attempt >= i.max_retries {
                        return Ok(resp);
                    }
                    let hint = retry_after(resp.headers().get("retry-after"));
                    tokio::time::sleep(self.delay(attempt, hint)).await;
                }
                Err(e) => {
                    if !retry || attempt >= i.max_retries {
                        return Err(net_err(e));
                    }
                    tokio::time::sleep(self.delay(attempt, None)).await;
                }
            }
            attempt += 1;
        }
    }

    fn delay(&self, attempt: u32, hint: Option<Duration>) -> Duration {
        if let Some(h) = hint {
            return h.min(Duration::from_secs(30));
        }
        let ms = self.inner.backoff_base.as_millis() as u64 * (1u64 << attempt.min(10));
        let jitter = rand::thread_rng().gen_range(0..=(ms / 4).max(1));
        Duration::from_millis((ms + jitter).min(20_000))
    }

    async fn status_error(&self, resp: reqwest::Response) -> Error {
        let status = resp.status().as_u16();
        let ra = retry_after(resp.headers().get("retry-after"));
        let body = resp.text().await.unwrap_or_default();
        let mut detail: String = body.chars().take(300).collect();
        if let Ok(Value::Object(m)) = serde_json::from_str::<Value>(&body) {
            let e = m.get("error").or_else(|| m.get("message"));
            match e {
                Some(Value::String(s)) => detail = s.clone(),
                Some(Value::Object(o)) => {
                    if let Some(Value::String(s)) = o.get("message") {
                        detail = s.clone();
                    }
                }
                _ => {}
            }
        }
        match status {
            401 | 403 => Error::Auth {
                status,
                message: detail,
            },
            429 => Error::RateLimit {
                message: detail,
                retry_after: ra,
            },
            _ => Error::Transport {
                message: format!("HTTP {status}: {detail}"),
                status: Some(status),
            },
        }
    }
}

fn retry_after(v: Option<&HeaderValue>) -> Option<Duration> {
    v.and_then(|v| v.to_str().ok())
        .and_then(|s| s.trim().parse::<u64>().ok())
        .map(Duration::from_secs)
}

fn net_err(e: reqwest::Error) -> Error {
    // reqwest errors can embed the request URL, which in the token-in-path
    // form contains the token: strip it.
    let e = e.without_url();
    let kind = if e.is_timeout() {
        "request timed out"
    } else if e.is_connect() {
        "connection failed"
    } else {
        "network error"
    };
    Error::Transport {
        message: kind.to_string(),
        status: None,
    }
}

/// Merge a serializable options struct into an argument map.
pub(crate) fn merge_opts<T: serde::Serialize>(args: &mut Map<String, Value>, opts: &T) {
    if let Ok(Value::Object(m)) = serde_json::to_value(opts) {
        for (k, v) in m {
            args.insert(k, v);
        }
    }
}
