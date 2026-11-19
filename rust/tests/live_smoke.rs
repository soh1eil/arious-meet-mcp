//! LIVE smoke test. Read-only calls ONLY: the handshake, prompts/list, whoami, start_here and
//! context_list. Never add send_message, get_updates, read_messages, mark_read, ack_updates or
//! context_checkpoint here. Skipped unless ARIOUS_MCP_TOKEN is set.
use arious_meet_mcp::*;

#[tokio::test]
async fn live_read_only_tools() {
    if std::env::var("ARIOUS_MCP_TOKEN")
        .unwrap_or_default()
        .is_empty()
    {
        eprintln!("ARIOUS_MCP_TOKEN not set; skipping live smoke test");
        return;
    }
    let c = Client::from_env(None).unwrap();
    c.initialize().await.unwrap();
    assert!(!c.list_tools().await.unwrap().is_empty());
    let prompts = c.list_prompts().await.unwrap();
    assert!(prompts.iter().any(|p| p.name == "resume"));
    assert!(!c.whoami().await.unwrap().is_error);
    let start: StartHere = c.start_here().await.unwrap().decode().unwrap();
    assert!(!start.identity.agent_id.is_empty() && !start.do_now.is_empty());
    match c.context_list(Default::default()).await {
        Ok(r) => assert!(r.data()["contexts"].is_array()),
        // the owner may have switched Arious Context off
        Err(Error::Tool { result, .. }) => {
            assert_eq!(result["structuredContent"]["contexts_enabled"], false)
        }
        Err(e) => panic!("{e}"),
    }
}
