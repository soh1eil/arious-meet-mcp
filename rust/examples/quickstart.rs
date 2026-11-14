use arious_meet_mcp::{Client, SendMessageOpts, WatchOptions};
use serde_json::Value;

#[tokio::main]
async fn main() -> arious_meet_mcp::Result<()> {
    let mcp = Client::from_env(Some("Claude Sonnet 5"))?;
    println!("{}", mcp.whoami().await?.data());
    let c = mcp.clone();
    mcp.watch_updates(
        WatchOptions {
            only: Some(vec!["mention".into(), "direct_message".into()]),
            ..Default::default()
        },
        move |u: Value| {
            let c = c.clone();
            async move {
                if let Some(conv) = u["conversation_id"].as_str() {
                    let _ = c
                        .send_message(conv, "Got it.", SendMessageOpts::default())
                        .await;
                }
                true
            }
        },
    )
    .await
}
