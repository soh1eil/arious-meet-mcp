//! Arious Context, start_here, prompts and platform updates against the shared mock.
mod common;

use arious_meet_mcp::*;
use common::{unique_token, Mock};
use serde_json::{json, Value};

async fn create(c: &Client, title: &str, goal: &str) -> String {
    let r = c
        .context_create(
            title,
            ContextCreateOpts {
                goal: Some(goal.into()),
                ..Default::default()
            },
        )
        .await
        .unwrap();
    r.data()["context"]["id"].as_str().unwrap().to_string()
}

fn append(v: Value) -> ContextCheckpointOpts {
    ContextCheckpointOpts {
        append: Some(v),
        ..Default::default()
    }
}

#[tokio::test]
async fn resume_where_another_agent_left_off() {
    for mode in ["json", "sse"] {
        let m = Mock::start(mode);
        let token = unique_token();
        let writer = m.client_with(&token, Some("Agent A"));
        let reader = m.client_with(&token, Some("Agent B"));
        let cid = create(&writer, "Ship 0.3", "Release the SDK").await;
        let first: CheckpointResult = writer
            .context_checkpoint(
                1,
                &cid,
                ContextCheckpointOpts {
                    current_step: Some("Writing tests".into()),
                    append: Some(
                        json!({"done_steps": ["Spec read"], "next_steps": ["Run the suite"]}),
                    ),
                    ..Default::default()
                },
            )
            .await
            .unwrap()
            .decode()
            .unwrap();
        assert_eq!(first.version, 2, "{mode}");
        assert!(!first.conflict && !first.was_redacted());

        // newest active context
        let resume: ContextResume = reader
            .context_resume(Default::default())
            .await
            .unwrap()
            .decode()
            .unwrap();
        assert_eq!(resume.context_id, cid);
        assert_eq!(resume.version, 2);
        assert!(resume.can_write);
        assert_eq!(resume.scope.as_deref(), Some("personal"));
        assert!(resume.organization_id.is_none());
        assert!(resume.brief.contains("Where we are now: Writing tests"));
        assert!(resume.brief.contains("Next step: Run the suite"));
        let next: CheckpointResult = reader
            .context_checkpoint(
                resume.version,
                &cid,
                append(json!({"done_steps": ["Suite green"]})),
            )
            .await
            .unwrap()
            .decode()
            .unwrap();
        assert_eq!(next.version, 3);
        let got = reader
            .context_get(
                &cid,
                ContextGetOpts {
                    history: Some(2),
                    ..Default::default()
                },
            )
            .await
            .unwrap()
            .data();
        let v: ContextVersion = serde_json::from_value(got["version"].clone()).unwrap();
        assert_eq!(v.author.model, "Agent B");
        assert_eq!(v.done_steps, ["Spec read", "Suite green"]);
        assert_eq!(got["history"][0]["version"], 3);
        assert_eq!(got["history"][1]["version"], 2);
    }
}

#[tokio::test]
async fn checkpoint_redacts_secrets_and_reports_them() {
    let m = Mock::start("json");
    let c = m.client();
    let cid = create(&c, "T", "g").await;
    let res: CheckpointResult = c
        .context_checkpoint(
            1,
            &cid,
            ContextCheckpointOpts {
                notes: Some("use sk-abcdefghijklmnopqrstuvwxyz and password=hunter2 here".into()),
                ..Default::default()
            },
        )
        .await
        .unwrap()
        .decode()
        .unwrap();
    assert!(res.was_redacted());
    assert_eq!(res.redacted.len(), 2);
    assert!(res.redacted.contains(&Redaction {
        field: "notes".into(),
        kind: "api_key".into(),
        count: 1
    }));
    assert!(res.redacted.contains(&Redaction {
        field: "notes".into(),
        kind: "secret_value".into(),
        count: 1
    }));
    let got = c
        .context_get(&cid, Default::default())
        .await
        .unwrap()
        .data();
    let notes = got["version"]["notes"].as_str().unwrap();
    assert!(!notes.contains("hunter2"));
    assert!(notes.contains("[REDACTED:api_key]"));
}

#[tokio::test]
async fn lost_race_is_a_context_conflict_with_latest() {
    let m = Mock::start("json");
    let token = unique_token();
    let c = m.client_with(&token, Some("Test Model"));
    let cid = create(&c, "T", "g").await;
    m.control(
        "/__mock/context_write",
        json!({"token": token, "context_id": cid, "current_step": "elsewhere", "model": "Other"}),
    )
    .await;
    let err = c
        .context_checkpoint(
            1,
            &cid,
            ContextCheckpointOpts {
                current_step: Some("mine".into()),
                ..Default::default()
            },
        )
        .await
        .unwrap_err();
    match err {
        Error::ContextConflict {
            base_version,
            latest_version,
            latest,
            result,
            ..
        } => {
            assert_eq!((base_version, latest_version), (1, 2));
            let latest = latest.expect("latest");
            assert_eq!(latest.current_step, "elsewhere");
            assert_eq!(latest.author.model, "Other");
            assert_eq!(result["structuredContent"]["conflict"], true);
        }
        other => panic!("expected ContextConflict, got {other:?}"),
    }
    let ok: CheckpointResult = c
        .context_checkpoint(
            2,
            &cid,
            ContextCheckpointOpts {
                current_step: Some("mine".into()),
                ..Default::default()
            },
        )
        .await
        .unwrap()
        .decode()
        .unwrap();
    assert_eq!(ok.version, 3);
}

#[tokio::test]
async fn conflict_as_a_result_with_call_tool_raw() {
    let m = Mock::start("json");
    let token = unique_token();
    let c = m.client_with(&token, Some("Test Model"));
    let cid = create(&c, "T", "g").await;
    m.control(
        "/__mock/context_write",
        json!({"token": token, "context_id": cid}),
    )
    .await;
    let raw = c
        .call_tool_raw(
            "context_checkpoint",
            json!({"context_id": cid, "base_version": 1, "notes": "x"}),
        )
        .await
        .unwrap();
    assert!(raw.is_error);
    let res: CheckpointResult = raw.decode().unwrap();
    assert!(res.conflict);
    assert_eq!(res.base_version, Some(1));
    assert_eq!(res.latest_version, Some(2));
    assert_eq!(res.latest.unwrap().version, 2);
}

#[tokio::test]
async fn other_tool_errors_stay_plain_tool_errors() {
    let m = Mock::start("json");
    let c = m.client();
    match c.context_get("nope", Default::default()).await {
        Err(Error::Tool { message, .. }) => assert!(message.contains("not found")),
        other => panic!("{other:?}"),
    }
    match c.context_resume(Default::default()).await {
        Err(Error::Tool { message, .. }) => assert!(message.contains("no active context")),
        other => panic!("{other:?}"),
    }
}

#[tokio::test]
async fn list_search_status_and_validation() {
    let m = Mock::start("json");
    let c = m.client();
    let a = create(&c, "Alpha plan", "first goal").await;
    let b = create(&c, "Beta plan", "second goal").await;
    let ids = |v: Value| -> Vec<String> {
        v["contexts"]
            .as_array()
            .unwrap()
            .iter()
            .map(|x| x["id"].as_str().unwrap().to_string())
            .collect()
    };
    let mut all = ids(c.context_list(Default::default()).await.unwrap().data());
    all.sort();
    assert_eq!(all, [a.clone(), b.clone()]);
    c.context_set_status(&a, "paused", Default::default())
        .await
        .unwrap();
    let paused = c
        .context_list(ContextListOpts {
            status: Some("paused".into()),
            ..Default::default()
        })
        .await
        .unwrap()
        .data();
    assert_eq!(ids(paused), std::slice::from_ref(&a));
    let hit = c
        .context_search("second", Default::default())
        .await
        .unwrap()
        .data();
    assert_eq!(ids(hit), [b]);
    assert!(matches!(
        c.context_checkpoint(-1, &a, Default::default()).await,
        Err(Error::Tool { .. })
    ));
    assert!(matches!(
        c.context_set_status(&a, "archived", Default::default())
            .await,
        Err(Error::Tool { .. })
    ));
}

#[tokio::test]
async fn context_off_is_a_tool_error_with_the_reason() {
    let m = Mock::start("json");
    let token = unique_token();
    let c = m.client_with(&token, Some("Test Model"));
    m.control(
        "/__mock/contexts",
        json!({"token": token, "enabled": false}),
    )
    .await;
    match c.context_list(Default::default()).await {
        Err(Error::Tool { result, .. }) => assert_eq!(
            result["structuredContent"],
            json!({"contexts_enabled": false, "reason": "turned_off_by_owner"})
        ),
        other => panic!("{other:?}"),
    }
    let s: StartHere = c.start_here().await.unwrap().decode().unwrap();
    assert!(!s.last_context.enabled);
    m.control("/__mock/contexts", json!({"token": token, "enabled": true}))
        .await;
    assert!(c.context_list(Default::default()).await.is_ok());
}

#[tokio::test]
async fn organization_scope_and_classification() {
    let m = Mock::start("json");
    let c = m.client();
    let personal = create(&c, "Mine", "g").await;
    let org = c
        .context_create(
            "Board pack",
            ContextCreateOpts {
                goal: Some("g".into()),
                organization_id: Some("org-1".into()),
                classification: Some("confidential".into()),
                ..Default::default()
            },
        )
        .await
        .unwrap()
        .data();
    assert_eq!(org["context"]["scope"], "organization");
    assert_eq!(org["context"]["classification"], "confidential");
    let oid = org["context"]["id"].as_str().unwrap().to_string();
    let mine = c.context_list(Default::default()).await.unwrap().data();
    assert_eq!(mine["contexts"].as_array().unwrap().len(), 1);
    assert_eq!(mine["contexts"][0]["id"], personal);
    let listed = c
        .context_list(ContextListOpts {
            organization_id: Some("org-1".into()),
            ..Default::default()
        })
        .await
        .unwrap()
        .data();
    assert_eq!(listed["scope"], "organization");
    assert_eq!(listed["contexts"][0]["id"], oid);
    let res: ContextResume = c
        .context_resume(ContextResumeOpts {
            context_id: Some(oid),
            organization_id: Some("org-1".into()),
            conversation_id: Some("conv-1".into()),
        })
        .await
        .unwrap()
        .decode()
        .unwrap();
    assert_eq!(res.scope.as_deref(), Some("organization"));
    assert_eq!(res.organization_id.as_deref(), Some("org-1"));
    assert_eq!(res.classification.as_deref(), Some("confidential"));
    match c
        .context_create(
            "S",
            ContextCreateOpts {
                organization_id: Some("org-1".into()),
                classification: Some("secret".into()),
                ..Default::default()
            },
        )
        .await
    {
        Err(Error::Tool { message, .. }) => assert!(message.contains("clearance")),
        other => panic!("{other:?}"),
    }
    match c
        .context_list(ContextListOpts {
            organization_id: Some("org-9".into()),
            ..Default::default()
        })
        .await
    {
        Err(Error::Tool { message, .. }) => assert!(message.contains("organization not found")),
        other => panic!("{other:?}"),
    }
}

#[tokio::test]
async fn start_here_is_typed_and_updates_are_acked_by_id() {
    let m = Mock::start("json");
    let c = m.client();
    let cid = create(&c, "Resume me", "goal").await;
    let r = c.start_here().await.unwrap();
    assert!(r.text.starts_with("START HERE"));
    let s: StartHere = r.decode().unwrap();
    assert_eq!(s.identity.name, "Mock Agent");
    assert!(s.last_context.enabled);
    assert_eq!(s.last_context.context_id.as_deref(), Some(cid.as_str()));
    assert!(s
        .last_context
        .brief
        .as_deref()
        .unwrap()
        .contains("Resume me"));
    assert_eq!(s.platform_updates.unread_count, 2);
    assert_eq!(s.important_update_ids(), ["upd-context"]);
    assert_eq!(s.conversations[0].id, "conv-1");
    assert!(!s.house_rules.is_empty() && !s.do_now.is_empty());
    c.ack_updates(AckUpdatesOpts {
        update_ids: Some(vec!["upd-context".into()]),
        ..Default::default()
    })
    .await
    .unwrap();
    let again: StartHere = c.start_here().await.unwrap().decode().unwrap();
    assert!(again.important_update_ids().is_empty());
    assert!(matches!(
        c.ack_updates(Default::default()).await,
        Err(Error::Tool { .. })
    ));
}

#[tokio::test]
async fn prompts_list_and_get() {
    let m = Mock::start("json");
    let c = m.client();
    let prompts = c.list_prompts().await.unwrap();
    let names: Vec<&str> = prompts.iter().map(|p| p.name.as_str()).collect();
    assert_eq!(names, ["start", "resume"]);
    assert!(prompts[0].arguments.is_empty());
    let args: Vec<(&str, bool)> = prompts[1]
        .arguments
        .iter()
        .map(|a| (a.name.as_str(), a.required))
        .collect();
    assert_eq!(args, [("context_id", false), ("organization_id", false)]);
    let cid = create(&c, "Prompted", "g").await;
    let res = c.get_prompt("resume", [("context_id", cid)]).await.unwrap();
    assert_eq!(res.messages[0].role, "user");
    assert!(res.text().contains("Title: Prompted"));
    let none: [(&str, &str); 0] = [];
    assert!(c
        .get_prompt("start", none)
        .await
        .unwrap()
        .text()
        .contains("START HERE"));
    match c.get_prompt("nope", none).await {
        Err(Error::Protocol { code, .. }) => assert_eq!(code, Some(-32602)),
        other => panic!("{other:?}"),
    }
}

#[tokio::test]
async fn context_reminder_and_platform_update_items() {
    let m = Mock::start("json");
    let token = unique_token();
    let c = m.client_with(&token, Some("Test Model"));
    m.push(
        &token,
        json!([
            {"kind": "message", "conversation_id": "c1", "message_id": "m1", "text": "hi"},
            {"kind": "platform_update", "id": "upd-x", "title": "New", "importance": "important"}
        ]),
    )
    .await;
    let res = c.get_updates(Default::default()).await.unwrap();
    assert!(res
        .context_reminder()
        .unwrap()
        .contains("context_checkpoint"));
    let pu = res.platform_updates();
    assert_eq!(pu.len(), 1);
    assert_eq!(pu[0].id, "upd-x");
    assert!(pu[0].is_important());
    assert!(c
        .read_messages("c1", Default::default())
        .await
        .unwrap()
        .context_reminder()
        .is_some());
    assert!(c
        .get_message("c1", "m1")
        .await
        .unwrap()
        .context_reminder()
        .is_some());
    assert!(c
        .read_messages("empty", Default::default())
        .await
        .unwrap()
        .context_reminder()
        .is_none());
    m.control(
        "/__mock/contexts",
        json!({"token": token, "enabled": false}),
    )
    .await;
    assert!(c
        .get_updates(Default::default())
        .await
        .unwrap()
        .context_reminder()
        .is_none());
}
