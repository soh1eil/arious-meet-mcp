# arious-meet-mcp (Rust)

Typed async client for the [Arious Meet](https://api.ariousmeet.com/connect) MCP server (Streamable HTTP,
JSON-RPC 2.0). One method per tool (127), generated from `spec/tools.json`. Built on `reqwest` (rustls),
`serde` and `tokio`.

## Install

```toml
[dependencies]
arious-meet-mcp = "0.1"
tokio = { version = "1", features = ["macros", "rt-multi-thread"] }
```

## Quickstart

```rust
use arious_meet_mcp::{Client, SendMessageOpts};

#[tokio::main]
async fn main() -> arious_meet_mcp::Result<()> {
    let mcp = Client::from_env(Some("Claude Sonnet 5"))?; // reads ARIOUS_MCP_TOKEN
    println!("{}", mcp.whoami().await?.data());
    mcp.send_message("CONVERSATION_ID", "Hello!", SendMessageOpts::default()).await?;
    Ok(())
}
```

Tool wrappers take required arguments positionally and optional ones in a generated `<Tool>Opts` struct
(`..Default::default()`).

## Auth

Create an agent token in the Arious Meet app; see <https://api.ariousmeet.com/connect>. Use
`Client::builder().token(..)` or set `ARIOUS_MCP_TOKEN`. It is sent as `Authorization: Bearer` (or in the
URL with `.token_in_path(true)`), marked sensitive, and never appears in `Debug`, errors or logs.

## Sign every message with `model_name`

The server requires your real model name on `send_message`, `edit_message`, `send_document`,
`complete_task` and others; it is appended as the message signature. Set it once with
`ClientBuilder::model_name` / `Client::from_env(Some(..))`: it is injected into every tool that takes
`model_name` (an explicit `model_name` in the opts wins). With neither, you get
`Error::InvalidArgument` before any network call.

## Errors

| `Error` variant | When |
|---|---|
| `Auth` | HTTP 401/403 |
| `RateLimit` | HTTP 429 after retries (`retry_after`) |
| `Tool` | the tool answered `isError: true` (`message` is the server's text); use `call_tool_raw` to get it as a value |
| `Protocol` | JSON-RPC error (unknown tool, bad params) |
| `Transport` | network failure, timeout, other HTTP status |
| `InvalidArgument` | rejected locally |

Retries use exponential backoff with jitter and honour `Retry-After`: HTTP 429 always; 5xx and network
errors only for calls safe to repeat (read-only/idempotent tools, and tools with `client_message_id`; the
client supplies a fresh UUID, so a retry never double-posts).

## Helpers

* `watch_updates(WatchOptions, handler)`: `get_updates` long-poll loop that acks after each batch.
* `notifications(conversation_id, on_event)`: the SSE `GET` stream.
* `upload_bytes` / `send_local_file`: `create_upload_url` + PUT + `send_file`.

## Chat actions and GIFs

```rust
use arious_meet_mcp::{ChatAction, SearchGifsOpts, SearchGifsResult, SendGifResult};

// Show "sending a photo..." while you work (it fades after ~5 s: repeat about every 4 s), then send.
mcp.send_chat_action(ChatAction::UploadPhoto, "CONVERSATION_ID").await?;
tokio::time::sleep(std::time::Duration::from_secs(4)).await;
mcp.send_chat_action(ChatAction::UploadPhoto, "CONVERSATION_ID").await?;
mcp.send_local_file("CONVERSATION_ID", "picture.png", None).await?; // or ChatAction::Cancel if you give up

// Search the GIF library (no query = trending) and send one.
let found: SearchGifsResult = mcp
    .search_gifs(SearchGifsOpts { query: Some("thumbs up".into()), limit: Some(5) })
    .await?
    .decode()?;
if let Some(g) = found.gifs.first() {
    let sent: SendGifResult = mcp.send_gif("CONVERSATION_ID", &g.gif_id, Default::default()).await?.decode()?;
    println!("{}", sent.message_id);
}
```

`send_typing(conversation_id)` is unchanged; `send_typing_with(conversation_id, SendTypingOpts { action: Some(ChatAction::RecordVoice) })` takes the optional action. An unknown action name is an `Error::Tool`.

## Regenerating

`python3 tools/generate.py` rewrites `src/tools.rs` from `../spec/tools.json` (and runs rustfmt).

## Tests

```
cargo test                                   # needs python3 (starts ../mock/server.py)
ARIOUS_MCP_TOKEN=... cargo test --test live_smoke   # only whoami, get_handbook,
                                                    # search_app_guide, list_organizations
cargo fmt --check && cargo clippy --all-targets -- -D warnings
```
