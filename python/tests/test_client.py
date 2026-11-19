import httpx
import pytest

from arious_meet_mcp import (
    AuthError,
    ChatAction,
    Client,
    ConfigError,
    ProtocolError,
    RateLimitError,
    SearchGifsResult,
    SendGifResult,
    ServerError,
    ToolError,
    TransportError,
)


def mk(url, token, mode="json", **kw):
    kw.setdefault("backoff", 0.01)
    c = Client(token, url=url, model_name="Test Model", **kw)
    c._http.headers["X-Mock-Mode"] = mode
    return c


@pytest.mark.parametrize("mode", ["json", "sse"])
def test_handshake_list_and_call(mock_url, token, mode):
    c = mk(mock_url, token, mode)
    tools = c.list_tools()
    assert len(tools) == 143
    assert c.server_info["name"] == "arious-agents"
    me = c.whoami()
    assert me.data["display_name"] == "Mock Agent"
    assert c.list_organizations().data["organizations"][0]["id"] == "org-1"
    assert c.get_handbook().text.startswith("# Handbook")
    assert "formatting" in c.get_handbook(section="formatting").text
    assert c.search_app_guide(query="calls").data["results"]


def test_session_id_is_sent_back(mock_url, token):
    c = mk(mock_url, token)
    c.whoami()
    assert c._session_id and c._session_id.startswith("sess-")


def test_path_token_form(mock_url, token):
    c = Client(url=mock_url + "/t/" + token, backoff=0.01)
    assert c.whoami().data["agent_id"] == "agent-1"


def test_auth_error_no_retry(mock_url):
    c = mk(mock_url, "wrong-token")
    with pytest.raises(AuthError) as e:
        c.whoami()
    assert e.value.status == 401
    assert "wrong-token" not in str(e.value)


def test_config_errors(monkeypatch):
    monkeypatch.delenv("ARIOUS_MCP_TOKEN", raising=False)
    with pytest.raises(ConfigError):
        Client()
    c = Client("x", url="http://127.0.0.1:1")
    with pytest.raises(ConfigError, match="model_name"):
        c.call_tool("send_message", {"conversation_id": "c", "text": "t"})


def test_env_token(monkeypatch, mock_url, token):
    monkeypatch.setenv("ARIOUS_MCP_TOKEN", token)
    assert Client(url=mock_url).whoami().data["agent_id"] == "agent-1"


def test_tool_error_and_protocol_error(mock_url, token):
    c = mk(mock_url, token)
    with pytest.raises(ToolError, match="tool-level"):
        c.call_tool("mock_tool_error")
    with pytest.raises(ProtocolError) as e:
        c.call_tool("mock_protocol_error")
    assert e.value.code == -32602
    with pytest.raises(ProtocolError):
        c.call_tool("does_not_exist")
    soft = mk(mock_url, token, raise_on_tool_error=False)
    r = soft.call_tool("mock_tool_error")
    assert r.is_error and "tool-level" in r.text


def test_tool_missing_required_arg_is_tool_error(mock_url, token):
    with pytest.raises(ToolError):
        mk(mock_url, token).call_tool("search_app_guide", {})


@pytest.mark.parametrize("mode,exc", [("error", ServerError), ("ratelimit", RateLimitError)])
def test_retry_then_success(mock_url, token, mode, exc):
    c = mk(mock_url, token, mode)
    assert c.whoami().data["agent_id"] == "agent-1"  # 2 failures then ok (3 retries)
    c2 = mk(mock_url, "test-" + token, mode, max_retries=1)
    with pytest.raises(exc):
        c2.whoami()


def test_ratelimit_retry_after_exposed(mock_url, token):
    c = mk(mock_url, token, "ratelimit", max_retries=0)
    with pytest.raises(RateLimitError) as e:
        c.whoami()
    assert e.value.retry_after == 0.0


def test_non_idempotent_5xx_not_retried_without_message_id(mock_url, token):
    # create_upload_url is neither read-only nor idempotent and has no client_message_id.
    c = mk(mock_url, token, "error")
    with pytest.raises(ServerError):
        c.create_upload_url(conversation_id="c1", filename="a.txt", size=3)
    # but 429 is always safe to retry
    c = mk(mock_url, "test-" + token, "ratelimit")
    assert c.create_upload_url(conversation_id="c1", filename="a.txt", size=3).data["upload_id"]


def test_send_message_signs_and_is_idempotent_under_retry(mock_url, token):
    c = mk(mock_url, token, "error")  # first 2 attempts 500, retried safely
    m = c.send_message("conv-1", "hello")
    assert m.data["text"].endswith("Test Model")
    again = mk(mock_url, token).send_message("conv-1", "hello", client_message_id="fixed-1")
    dup = mk(mock_url, token).send_message("conv-1", "hello", client_message_id="fixed-1")
    assert dup.data["deduplicated"] is True
    assert dup.data["message_id"] == again.data["message_id"]


def test_explicit_model_name_wins(mock_url, token):
    m = mk(mock_url, token).send_message("c", "x", model_name="Other")
    assert m.data["text"].endswith("Other")


def test_transport_error(token):
    c = Client(token, url="http://127.0.0.1:1/v1/mcp", max_retries=1, backoff=0.01)
    with pytest.raises(TransportError):
        c.whoami()


def test_watch_updates_acks_after_batch(mock_url, token):
    c = mk(mock_url, token)
    httpx.post(
        mock_url.replace("/v1/mcp", "") + "/__mock/push",
        json={
            "token": token,
            "items": [{"kind": "mention", "text": "a"}, {"kind": "mention", "text": "b"}],
        },
    )
    seen = []
    for u in c.watch_updates(wait_seconds=0):
        seen.append(u["text"])
        if len(seen) == 2:
            break
    assert seen == ["a", "b"]
    # Breaking mid-batch means the batch was never acknowledged: it replays.
    again = c.get_updates().data["updates"]
    assert [u["text"] for u in again] == ["a", "b"]
    # Finishing a batch acks it.
    gen = c.watch_updates(wait_seconds=0)
    got = [next(gen), next(gen)]
    assert len(got) == 2
    httpx.post(
        mock_url.replace("/v1/mcp", "") + "/__mock/push",
        json={"token": token, "items": [{"kind": "mention", "text": "c"}]},
    )
    assert next(gen)["text"] == "c"  # resuming past the first batch acked it
    assert [u["text"] for u in c.get_updates().data["updates"]] == ["c"]  # a, b acked; c not yet


def mock_actions(mock_url):
    r = httpx.get(mock_url.rsplit("/v1/mcp", 1)[0] + "/__mock/log")
    return r.json()


def test_chat_action_enum_values():
    assert len(ChatAction) == 11
    assert ChatAction.UPLOAD_PHOTO.value == "upload_photo"
    assert ChatAction.CANCEL.value == "cancel"


@pytest.mark.parametrize("mode", ["json", "sse"])
def test_send_chat_action_and_typing(mock_url, token, mode):
    c = mk(mock_url, token, mode)
    c.send_chat_action("conv-act", ChatAction.UPLOAD_PHOTO)
    c.send_chat_action("conv-act", ChatAction.CANCEL)
    c.send_typing("conv-act")  # backward compatible: no action means typing
    c.send_typing("conv-act", action=ChatAction.RECORD_VOICE)
    mine = [a for a in mock_actions(mock_url)["actions"] if a["conversation_id"] == "conv-act"]
    assert [a["action"] for a in mine][-4:] == ["upload_photo", "cancel", "typing", "record_voice"]


def test_unknown_chat_action_is_tool_error(mock_url, token):
    c = mk(mock_url, token)
    with pytest.raises(ToolError) as e:
        c.send_chat_action("conv-bad", "dance")  # type: ignore[arg-type]
    assert "unknown action" in str(e.value)
    with pytest.raises(ToolError):
        c.send_typing("conv-bad", action="dance")  # type: ignore[arg-type]


def test_search_and_send_gif(mock_url, token):
    c = mk(mock_url, token)
    trending = SearchGifsResult.from_result(c.search_gifs())
    assert len(trending.gifs) == 6 and not trending.busy
    found = SearchGifsResult.from_result(c.search_gifs(query="thumbs up", limit=1))
    assert [g.gif_id for g in found.gifs] == ["gif-001"]
    g = found.gifs[0]
    assert (g.width, g.height, g.content_type, g.source) == (480, 270, "image/gif", "library")
    assert g.preview_url and g.preview_url.startswith("http")
    assert SearchGifsResult.from_result(c.search_gifs(query="busy")).busy
    sent = SendGifResult.from_result(
        c.send_gif("conv-gif", g.gif_id, caption="nice", reply_to_id="m1", silent=True)
    )
    assert sent.gif_id == "gif-001" and sent.conversation_id == "conv-gif"
    assert sent.message_id.startswith("msg-gif-") and sent.attachment_id.startswith("att-gif-")
    assert sent.sent_via_grant_name is None


def test_gif_errors(mock_url, token):
    c = mk(mock_url, token)
    with pytest.raises(ToolError):
        c.search_gifs(limit=26)
    with pytest.raises(ToolError):
        c.send_gif("conv-gif", "nope")
    c2 = Client(token, url=mock_url, backoff=0.01)  # no model_name configured
    with pytest.raises(ConfigError):
        c2.send_gif("conv-gif", "gif-001")
