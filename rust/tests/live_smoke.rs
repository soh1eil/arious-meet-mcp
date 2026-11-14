//! LIVE smoke test: calls ONLY whoami, get_handbook, search_app_guide and
//! list_organizations. Skipped unless ARIOUS_MCP_TOKEN is set.
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
    assert!(!c.whoami().await.unwrap().is_error);
    let h = c
        .get_handbook(GetHandbookOpts {
            section: Some("formatting".into()),
        })
        .await
        .unwrap();
    assert!(!h.text.is_empty());
    assert!(
        !c.search_app_guide("calls", Default::default())
            .await
            .unwrap()
            .is_error
    );
    assert!(!c.list_organizations().await.unwrap().is_error);
}
