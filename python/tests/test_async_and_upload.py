import httpx
import pytest

from arious_meet_mcp import (
    AsyncClient,
    AuthError,
    ChatAction,
    Client,
    ConfigError,
    SearchGifsResult,
    SendGifResult,
    ToolError,
)


def base(mock_url):
    return mock_url.replace("/v1/mcp", "")


async def test_async_basic_and_sse(mock_url, token):
    async with AsyncClient(token, url=mock_url, model_name="M", backoff=0.01) as c:
        c._http.headers["X-Mock-Mode"] = "sse"
        assert len(await c.list_tools()) == 127
        assert (await c.whoami()).data["agent_id"] == "agent-1"
        m = await c.send_message("conv", "hi")
        assert m.data["text"].endswith("M")
        with pytest.raises(ToolError):
            await c.call_tool("mock_tool_error")


async def test_async_retry_and_auth(mock_url, token):
    async with AsyncClient(token, url=mock_url, backoff=0.01) as c:
        c._http.headers["X-Mock-Mode"] = "ratelimit"
        assert (await c.whoami()).data["agent_id"] == "agent-1"
    async with AsyncClient("bad", url=mock_url) as c:
        with pytest.raises(AuthError):
            await c.whoami()


async def test_async_watch(mock_url, token):
    httpx.post(
        base(mock_url) + "/__mock/push",
        json={"token": token, "items": [{"kind": "mention", "text": "z"}]},
    )
    async with AsyncClient(token, url=mock_url, backoff=0.01) as c:
        async for u in c.watch_updates(wait_seconds=0):
            assert u["text"] == "z"
            break


def test_upload_bytes_path_and_fileobj(mock_url, token, tmp_path):
    c = Client(token, url=mock_url, model_name="M", backoff=0.01)
    r = c.upload_and_send("conv", b"hello", filename="a.txt")
    assert r.data["size_bytes"] == 5
    p = tmp_path / "b.bin"
    p.write_bytes(b"x" * 1000)
    assert c.upload_and_send("conv", p, caption="c").data["size_bytes"] == 1000
    with open(p, "rb") as fh:
        assert c.upload_and_send("conv", fh, filename="b.bin").data["size_bytes"] == 1000
    t = c.upload_and_send("conv", b"abc", filename="c.txt", send=False)
    assert t.data["upload_id"].startswith("up-")
    with pytest.raises(ConfigError):
        c.upload_and_send("conv", b"abc")


async def test_async_upload(mock_url, token):
    async with AsyncClient(token, url=mock_url, model_name="M") as c:
        r = await c.upload_and_send("conv", b"hello!", filename="a.txt")
        assert r.data["size_bytes"] == 6


async def test_async_chat_action_and_gif(mock_url, token):
    async with AsyncClient(token, url=mock_url, model_name="M", backoff=0.01) as c:
        await c.send_chat_action("conv-async", ChatAction.UPLOAD_VIDEO)
        await c.send_typing("conv-async", action=ChatAction.CANCEL)
        with pytest.raises(ToolError):
            await c.send_chat_action("conv-async", "dance")  # type: ignore[arg-type]
        found = SearchGifsResult.from_result(await c.search_gifs(query="applause"))
        assert [g.gif_id for g in found.gifs] == ["gif-003"]
        sent = SendGifResult.from_result(await c.send_gif("conv-async", "gif-003"))
        assert sent.gif_id == "gif-003"
    log = httpx.get(base(mock_url) + "/__mock/log").json()["actions"]
    mine = [a["action"] for a in log if a["conversation_id"] == "conv-async"]
    assert mine == ["upload_video", "cancel"]
