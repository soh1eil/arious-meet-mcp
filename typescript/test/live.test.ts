// Live smoke test against the real server. Read-only tools ONLY (whoami, get_handbook,
// search_app_guide, list_organizations). Never add send_message / get_updates /
// read_messages / mark_read / ack_updates here: they change state or mark messages read.
import assert from "node:assert/strict";
import { it } from "node:test";
import { AriousClient } from "@arious-meet/mcp";

it("live: read-only tools", { skip: !process.env.ARIOUS_MCP_TOKEN }, async () => {
  const c = new AriousClient({ timeoutMs: 30_000 });
  assert.ok((await c.listTools()).length > 100);
  assert.ok((await c.whoami()).data);
  assert.ok((await c.getHandbook()).text.length > 500);
  assert.ok((await c.searchAppGuide({ query: "how do I create a group", lang: "en" })).text);
  assert.notEqual((await c.listOrganizations()).text, undefined);
});
