"""Live smoke test against the real server. Read-only calls ONLY.

Run: ARIOUS_MCP_TOKEN=... pytest -m live tests/test_live.py
Allowed: the handshake, prompts/list, whoami, start_here and context_list. Never add
another tool here: send_message / get_updates / read_messages / mark_read / ack_updates /
context_checkpoint change state or mark the owner's messages as read.
"""

import os

import pytest

from arious_meet_mcp import Client, StartHere, ToolError

pytestmark = pytest.mark.live


@pytest.mark.skipif(not os.environ.get("ARIOUS_MCP_TOKEN"), reason="ARIOUS_MCP_TOKEN not set")
def test_live_readonly_tools():
    with Client(timeout=30) as c:
        assert len(c.list_tools()) > 100
        assert {p.name for p in c.list_prompts()} >= {"start", "resume"}
        assert c.whoami().data
        start = StartHere.from_result(c.start_here())
        assert start.agent_id and start.do_now and start.text
        try:
            assert "contexts" in c.context_list().data
        except ToolError as e:  # the owner may have switched Arious Context off
            assert (e.result.structured or {}).get("contexts_enabled") is False
