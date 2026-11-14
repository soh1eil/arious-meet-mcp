mod common;

use arious_meet_mcp::*;
use common::{unique_token, Mock};
use serde_json::{json, Value};

#[tokio::test]
async fn handshake_lists_all_tools_in_both_modes() {
    for mode in ["json", "sse"] {
        let m = Mock::start(mode);
        let c = m.client();
        let info = c.initialize().await.unwrap();
        assert!(info["serverInfo"].is_object(), "{mode}");
        let tools = c.list_tools().await.unwrap();
        assert_eq!(tools.len(), 124, "{mode}");
        let names: Vec<&str> = tools.iter().filter_map(|t| t["name"].as_str()).collect();
        for n in TOOL_NAMES {
            assert!(names.contains(n), "missing {n}");
        }
        assert_eq!(TOOL_NAMES.len(), 124);
    }
}

#[tokio::test]
async fn read_only_tools_in_both_modes() {
    for mode in ["json", "sse"] {
        let m = Mock::start(mode);
        let c = m.client();
        assert_eq!(
            c.whoami().await.unwrap().data()["display_name"],
            "Mock Agent",
            "{mode}"
        );
        let h = c
            .get_handbook(GetHandbookOpts {
                section: Some("tasks".into()),
            })
            .await
            .unwrap();
        assert!(h.structured.is_none());
        assert!(h.text.contains("tasks"));
        let g = c
            .search_app_guide("calls", Default::default())
            .await
            .unwrap();
        assert!(!g.data()["results"].as_array().unwrap().is_empty());
        let o = c.list_organizations().await.unwrap();
        assert!(!o.data()["organizations"].as_array().unwrap().is_empty());
    }
}

#[tokio::test]
async fn bad_token_is_auth_error_without_leak() {
    let m = Mock::start("json");
    let c = m.client_with("wrong-secret-token", None);
    match c.whoami().await {
        Err(e @ Error::Auth { status: 401, .. }) => {
            assert!(!e.to_string().contains("wrong-secret-token"));
            assert!(!format!("{c:?}").contains("wrong-secret-token"));
        }
        other => panic!("expected auth error, got {other:?}"),
    }
}

#[tokio::test]
async fn tool_and_protocol_errors() {
    let m = Mock::start("json");
    let c = m.client();
    match c.call_tool("mock_tool_error", Value::Null).await {
        Err(Error::Tool { message, .. }) => assert!(message.contains("tool-level")),
        other => panic!("{other:?}"),
    }
    assert!(
        c.call_tool_raw("mock_tool_error", Value::Null)
            .await
            .unwrap()
            .is_error
    );
    match c.call_tool("mock_protocol_error", Value::Null).await {
        Err(Error::Protocol {
            code: Some(-32602), ..
        }) => {}
        other => panic!("{other:?}"),
    }
    assert!(matches!(
        c.call_tool("no_such_tool_at_all", Value::Null).await,
        Err(Error::Protocol { .. })
    ));
}

#[tokio::test]
async fn local_argument_checks() {
    assert!(matches!(
        Client::builder().token("  ").build(),
        Err(Error::InvalidArgument(_))
    ));
    let m = Mock::start("json");
    let c = m.client_with(&unique_token(), None);
    let r = c.send_message("c1", "x", Default::default()).await;
    assert!(matches!(r, Err(Error::InvalidArgument(_))));
}

#[tokio::test]
async fn network_error_is_transport() {
    let c = Client::builder()
        .token("test-x")
        .base_url("http://127.0.0.1:1/v1/mcp")
        .max_retries(1)
        .backoff_base(std::time::Duration::from_millis(1))
        .build()
        .unwrap();
    assert!(matches!(c.whoami().await, Err(Error::Transport { .. })));
}

#[tokio::test]
async fn rate_limit_is_retried_then_succeeds() {
    let m = Mock::start("ratelimit");
    let c = m.client();
    assert!(!c.whoami().await.unwrap().is_error);
    let n = m
        .log()
        .await
        .iter()
        .filter(|e| e.to_string().contains("whoami"))
        .count();
    assert!(n >= 3, "expected 2 rejected + 1 accepted, saw {n}");
}

#[tokio::test]
async fn rate_limit_exhausted() {
    let m = Mock::start("ratelimit");
    let c = Client::builder()
        .token(unique_token())
        .base_url(m.url.clone())
        .max_retries(1)
        .backoff_base(std::time::Duration::from_millis(1))
        .build()
        .unwrap();
    assert!(matches!(c.whoami().await, Err(Error::RateLimit { .. })));
}

#[tokio::test]
async fn http_500_retry_rules() {
    let m = Mock::start("error");
    // read-only: retried
    assert!(!m.client().whoami().await.unwrap().is_error);
    // send_message: gets a client_message_id, so it is retried safely
    let r = m
        .client()
        .send_message("c1", "hello", Default::default())
        .await
        .unwrap();
    assert!(r.data()["text"].as_str().unwrap().contains("Test Model"));
    // a non-idempotent tool without any message id is NOT retried
    let m2 = Mock::start("error");
    let name = ["add_contact", "react", "ring", "call", "create_task_list"]
        .into_iter()
        .find(|n| {
            let t = tool_json(n);
            t.is_some()
        })
        .unwrap();
    let res = m2.client().call_tool(name, json!({})).await;
    assert!(
        matches!(
            res,
            Err(Error::Transport {
                status: Some(500),
                ..
            })
        ),
        "{res:?}"
    );
    let calls = m2
        .log()
        .await
        .iter()
        .filter(|e| e.to_string().contains("tools/call"))
        .count();
    assert_eq!(calls, 1, "must not retry {name}");
}

fn tool_json(name: &str) -> Option<()> {
    let spec: Value = serde_json::from_str(include_str!("../../spec/tools.json")).unwrap();
    let t = spec["tools"]
        .as_array()?
        .iter()
        .find(|t| t["name"] == name)?;
    let a = &t["annotations"];
    let safe = a["readOnlyHint"] == true || a["idempotentHint"] == true;
    let cmid = t["inputSchema"]["properties"]
        .get("client_message_id")
        .is_some();
    let mn = t["inputSchema"]["properties"].get("model_name").is_some();
    (!safe && !cmid && !mn).then_some(())
}

#[tokio::test]
async fn send_message_signs_and_dedupes() {
    let m = Mock::start("json");
    let c = m.client_with(&unique_token(), Some("Claude Test"));
    let opts = || SendMessageOpts {
        client_message_id: Some("abc-1".into()),
        ..Default::default()
    };
    let a = c.send_message("c1", "hi", opts()).await.unwrap().data();
    let b = c.send_message("c1", "hi", opts()).await.unwrap().data();
    assert_eq!(a["message_id"], b["message_id"]);
    assert_eq!(b["deduplicated"], true);
    assert!(a["text"].as_str().unwrap().ends_with("Claude Test"));
    let e = c
        .send_message(
            "c1",
            "hi",
            SendMessageOpts {
                model_name: Some("Explicit".into()),
                ..Default::default()
            },
        )
        .await
        .unwrap()
        .data();
    assert!(e["text"].as_str().unwrap().ends_with("Explicit"));
}

#[tokio::test]
async fn watch_updates_yields_and_acks() {
    let m = Mock::start("json");
    let tok = unique_token();
    let c = m.client_with(&tok, None);
    m.push(
        &tok,
        json!([
            {"kind": "mention", "conversation_id": "c1", "text": "one"},
            {"kind": "mention", "conversation_id": "c1", "text": "two"}
        ]),
    )
    .await;
    let mut got: Vec<Value> = vec![];
    let mut seen = 0;
    c.watch_updates(
        WatchOptions {
            wait_seconds: 1,
            ..Default::default()
        },
        |u| {
            got.push(u);
            seen += 1;
            let keep = seen < 2;
            async move { keep }
        },
    )
    .await
    .unwrap();
    assert_eq!(
        got.iter()
            .map(|u| u["text"].as_str().unwrap())
            .collect::<Vec<_>>(),
        ["one", "two"]
    );
}

#[tokio::test]
async fn upload_bytes_and_send_file() {
    let m = Mock::start("json");
    let c = m.client();
    let id = c
        .upload_bytes("c1", "a.txt", b"hello".to_vec(), Some("text/plain"))
        .await
        .unwrap();
    let r = c.send_file("c1", id, Default::default()).await.unwrap();
    assert_eq!(r.data()["size_bytes"], 5);
}

#[tokio::test]
async fn notifications_stream() {
    let m = Mock::start("json");
    let tok = unique_token();
    let c = m.client_with(&tok, None);
    m.push(
        &tok,
        json!([{"kind": "mention", "conversation_id": "c1", "text": "ping"}]),
    )
    .await;
    let mut events = vec![];
    c.notifications(None, |v| {
        events.push(v);
        true
    })
    .await
    .unwrap();
    assert_eq!(events[0]["method"], "notifications/resources/updated");
}

#[tokio::test]
async fn token_in_path_form() {
    let m = Mock::start("json");
    let c = Client::builder()
        .token(unique_token())
        .base_url(m.url.clone())
        .token_in_path(true)
        .build()
        .unwrap();
    assert!(!c.whoami().await.unwrap().is_error);
}

#[test]
fn sse_parser_handles_multiline_and_comments() {
    assert_eq!(
        parse_sse_data(": hi\n\ndata: a\ndata: b\n\ndata:c\n\n"),
        vec!["a\nb", "c"]
    );
    assert_eq!(parse_sse_data("data: tail"), vec!["tail"]);
}
