// Live smoke test against the real server. Read-only calls ONLY: the handshake, prompts/list,
// whoami, startHere and contextList. Never add sendMessage / getUpdates / readMessages /
// markRead / ackUpdates / contextCheckpoint here: they change state or mark messages read.
import assert from "node:assert/strict";
import { it } from "node:test";
import { AriousClient, ToolError } from "@arious-meet/mcp";
it("live: read-only tools", { skip: !process.env.ARIOUS_MCP_TOKEN }, async () => {
    const c = new AriousClient({ timeoutMs: 30_000 });
    assert.ok((await c.listTools()).length > 100);
    const names = (await c.listPrompts()).map((p) => p.name);
    assert.ok(names.includes("start") && names.includes("resume"));
    assert.ok((await c.whoami()).data);
    const start = await c.startHere();
    assert.ok(start.data.identity.agent_id && start.data.do_now.length > 0 && start.text);
    try {
        assert.ok(Array.isArray((await c.contextList()).data.contexts));
    }
    catch (e) {
        // the owner may have switched Arious Context off
        assert.ok(e instanceof ToolError && e.result.structured?.contexts_enabled === false);
    }
});
