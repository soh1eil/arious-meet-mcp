"""Arious Context, start_here, prompts and platform updates against the shared mock."""

import httpx
import pytest

from arious_meet_mcp import (
    AsyncClient,
    CheckpointResult,
    Client,
    ContextConflict,
    ContextResume,
    ProtocolError,
    StartHere,
    ToolError,
)


def mk(url, token, mode="json", **kw):
    kw.setdefault("backoff", 0.01)
    kw.setdefault("model_name", "Test Model")
    c = Client(token, url=url, **kw)
    c._http.headers["X-Mock-Mode"] = mode
    return c


def control(mock_url, path, body):
    base = mock_url.replace("/v1/mcp", "")
    httpx.post(base + path, json=body).raise_for_status()


def create(c, title="Ship 0.3", goal="Release the SDK", **kw):
    return c.context_create(title, goal=goal, **kw).data["context"]["id"]


@pytest.mark.parametrize("mode", ["json", "sse"])
def test_resume_where_another_agent_left_off(mock_url, token, mode):
    writer = mk(mock_url, token, mode, model_name="Agent A")
    cid = create(writer)
    first = CheckpointResult.from_result(
        writer.context_checkpoint(
            cid,
            1,
            current_step="Writing tests",
            append={"done_steps": ["Spec read"], "next_steps": ["Run the suite"]},
        )
    )
    assert first.version == 2 and not first.conflict and not first.was_redacted

    reader = mk(mock_url, token, mode, model_name="Agent B")
    resume = ContextResume.from_result(reader.context_resume())  # most recent active context
    assert resume.context_id == cid and resume.version == 2 and resume.can_write
    assert resume.scope == "personal" and resume.organization_id is None
    assert "Where we are now: Writing tests" in resume.brief
    assert "Next step: Run the suite" in resume.brief
    nxt = CheckpointResult.from_result(
        reader.context_checkpoint(cid, resume.version, append={"done_steps": ["Suite green"]})
    )
    assert nxt.version == 3
    got = reader.context_get(cid, history=2).data
    assert got["version"]["author"]["model"] == "Agent B"
    assert got["version"]["done_steps"] == ["Spec read", "Suite green"]
    assert [h["version"] for h in got["history"]] == [3, 2]


def test_checkpoint_redacts_secrets_and_reports_them(mock_url, token):
    c = mk(mock_url, token)
    cid = create(c)
    res = CheckpointResult.from_result(
        c.context_checkpoint(
            cid,
            1,
            notes="use sk-abcdefghijklmnopqrstuvwxyz and password=hunter2 here",
            decisions=[{"text": "ok", "why": "Bearer abcdefghijklmnopqrstuvwx"}],
        )
    )
    assert res.was_redacted
    kinds = {(r.field, r.kind): r.count for r in res.redacted}
    assert kinds[("notes", "api_key")] == 1 and kinds[("notes", "secret_value")] == 1
    assert kinds[("decisions", "bearer_token")] == 1
    stored = c.context_get(cid).data["version"]
    assert "hunter2" not in stored["notes"] and "[REDACTED:api_key]" in stored["notes"]
    assert stored["redactions"]


def test_conflict_raises_context_conflict_with_latest(mock_url, token):
    c = mk(mock_url, token)
    cid = create(c)
    control(
        mock_url,
        "/__mock/context_write",
        {"token": token, "context_id": cid, "current_step": "elsewhere", "model": "Other"},
    )
    with pytest.raises(ContextConflict) as e:
        c.context_checkpoint(cid, 1, current_step="mine")
    err = e.value
    assert isinstance(err, ToolError)  # old handlers keep working
    assert (err.base_version, err.latest_version) == (1, 2)
    assert err.latest is not None and err.latest.current_step == "elsewhere"
    assert err.latest.author.model == "Other"
    # merge onto the latest and retry
    ok = CheckpointResult.from_result(
        c.context_checkpoint(cid, err.latest_version, current_step="mine")
    )
    assert ok.version == 3


def test_conflict_as_result_when_not_raising(mock_url, token):
    c = mk(mock_url, token, raise_on_tool_error=False)
    cid = create(c)
    control(mock_url, "/__mock/context_write", {"token": token, "context_id": cid})
    raw = c.context_checkpoint(cid, 1, current_step="mine")
    assert raw.is_error
    res = CheckpointResult.from_result(raw)
    assert res.conflict and res.base_version == 1 and res.latest_version == 2
    assert res.latest is not None and res.latest.version == 2


def test_other_tool_errors_stay_plain_tool_errors(mock_url, token):
    c = mk(mock_url, token)
    with pytest.raises(ToolError) as e:
        c.context_get("nope")
    assert not isinstance(e.value, ContextConflict)
    assert "not found" in str(e.value)
    with pytest.raises(ToolError, match="no active context"):
        c.context_resume()


def test_list_search_status_and_validation(mock_url, token):
    c = mk(mock_url, token)
    a = create(c, "Alpha plan", "first goal")
    b = create(c, "Beta plan", "second goal")
    ids = [x["id"] for x in c.context_list().data["contexts"]]
    assert set(ids) == {a, b}
    c.context_set_status(a, "paused")
    assert [x["id"] for x in c.context_list(status="paused").data["contexts"]] == [a]
    hit = c.context_search("second").data["contexts"]
    assert [x["id"] for x in hit] == [b]
    assert c.context_list(limit=1).data["contexts"][0]["id"] in (a, b)
    with pytest.raises(ToolError):
        c.context_checkpoint(a, -1)
    with pytest.raises(ToolError):
        c.context_set_status(a, "archived")  # type: ignore[arg-type]


def test_context_off_is_a_tool_error_with_reason(mock_url, token):
    c = mk(mock_url, token)
    control(mock_url, "/__mock/contexts", {"token": token, "enabled": False})
    with pytest.raises(ToolError) as e:
        c.context_list()
    assert e.value.result.structured == {
        "contexts_enabled": False,
        "reason": "turned_off_by_owner",
    }
    assert StartHere.from_result(c.start_here()).contexts_enabled is False
    control(mock_url, "/__mock/contexts", {"token": token, "enabled": True})
    assert c.context_list().data["contexts"] == []


def test_organization_scope_and_classification(mock_url, token):
    c = mk(mock_url, token)
    personal = create(c, "Mine")
    org = c.context_create(
        "Board pack", goal="g", organization_id="org-1", classification="confidential"
    ).data
    oid = org["context"]["id"]
    assert org["context"]["scope"] == "organization"
    assert org["context"]["classification"] == "confidential"
    assert [x["id"] for x in c.context_list().data["contexts"]] == [personal]
    listed = c.context_list(organization_id="org-1").data
    assert listed["scope"] == "organization" and [x["id"] for x in listed["contexts"]] == [oid]
    res = ContextResume.from_result(c.context_resume(context_id=oid, organization_id="org-1"))
    assert res.scope == "organization" and res.organization_id == "org-1"
    assert res.classification == "confidential"
    with pytest.raises(ToolError, match="clearance"):
        c.context_create("Secret", organization_id="org-1", classification="secret")
    with pytest.raises(ToolError, match="clearance"):
        c.context_create("Personal conf", classification="confidential")
    with pytest.raises(ToolError, match="organization not found"):
        c.context_list(organization_id="org-9")
    # the conversation_id argument is accepted by context_resume
    assert c.context_resume(context_id=oid, organization_id="org-1", conversation_id="conv-1").data


def test_start_here_typed_and_ack_platform_updates(mock_url, token):
    c = mk(mock_url, token)
    cid = create(c, "Resume me", "goal")
    s = StartHere.from_result(c.start_here())
    assert s.name == "Mock Agent" and s.contexts_enabled and s.last_context_id == cid
    assert s.last_context_brief and "Resume me" in s.last_context_brief
    assert s.unread_updates == 2 and s.important_update_ids == ["upd-context"]
    assert s.conversations[0]["id"] == "conv-1" and s.house_rules and s.do_now
    assert s.text.startswith("START HERE")
    c.ack_updates(update_ids=s.important_update_ids)
    assert StartHere.from_result(c.start_here()).important_update_ids == []
    with pytest.raises(ToolError):
        c.ack_updates()  # neither cursor nor update_ids


def test_prompts_list_and_get(mock_url, token):
    c = mk(mock_url, token)
    prompts = {p.name: p for p in c.list_prompts()}
    assert set(prompts) == {"start", "resume"}
    assert [(a.name, a.required) for a in prompts["resume"].arguments] == [
        ("context_id", False),
        ("organization_id", False),
    ]
    assert prompts["start"].arguments == []
    cid = create(c, "Prompted", "g")
    res = c.get_prompt("resume", {"context_id": cid})
    assert res.messages[0].role == "user" and "Title: Prompted" in res.text
    assert "START HERE" in c.get_prompt("start").text
    with pytest.raises(ProtocolError) as e:
        c.get_prompt("nope")
    assert e.value.code == -32602


def test_context_reminder_and_platform_update_items(mock_url, token):
    c = mk(mock_url, token)
    control(
        mock_url,
        "/__mock/push",
        {
            "token": token,
            "items": [
                {"kind": "message", "conversation_id": "c1", "message_id": "m1", "text": "hi"},
                {
                    "kind": "platform_update",
                    "id": "upd-x",
                    "title": "New",
                    "importance": "important",
                },
            ],
        },
    )
    res = c.get_updates()
    assert res.context_reminder and "context_checkpoint" in res.context_reminder
    pu = res.platform_updates
    assert [(u.id, u.important) for u in pu] == [("upd-x", True)]
    assert c.read_messages("c1").context_reminder
    assert c.get_message("c1", "m1").context_reminder
    assert c.read_messages("empty").context_reminder is None
    control(mock_url, "/__mock/contexts", {"token": token, "enabled": False})
    assert c.get_updates().context_reminder is None


async def test_async_resume_conflict_and_prompts(mock_url, token):
    async with AsyncClient(token, url=mock_url, model_name="Async M", backoff=0.01) as c:
        cid = (await c.context_create("Async", goal="g")).data["context"]["id"]
        resume = ContextResume.from_result(await c.context_resume(context_id=cid))
        assert resume.version == 1
        control(mock_url, "/__mock/context_write", {"token": token, "context_id": cid})
        with pytest.raises(ContextConflict) as e:
            await c.context_checkpoint(cid, resume.version, notes="x")
        assert e.value.latest_version == 2
        assert {p.name for p in await c.list_prompts()} == {"start", "resume"}
        assert "Title: Async" in (await c.get_prompt("resume", {"context_id": cid})).text
        assert StartHere.from_result(await c.start_here()).contexts_enabled
