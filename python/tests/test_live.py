"""Live smoke test against the real server. Read-only tools ONLY.

Run: ARIOUS_MCP_TOKEN=... pytest -m live tests/test_live.py
Never add another tool here: send_message / get_updates / read_messages /
mark_read / ack_updates change state or mark the owner's messages as read.
"""

import os

import pytest

from arious_meet_mcp import Client

pytestmark = pytest.mark.live


@pytest.mark.skipif(not os.environ.get("ARIOUS_MCP_TOKEN"), reason="ARIOUS_MCP_TOKEN not set")
def test_live_readonly_tools():
    with Client(timeout=30) as c:
        assert len(c.list_tools()) > 100
        assert c.whoami().data
        assert len(c.get_handbook().text) > 500
        assert c.search_app_guide(query="how do I create a group", lang="en").text
        assert c.list_organizations().text is not None
