import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import {
  AriousClient,
  type CheckpointConflict,
  ContextConflict,
  ProtocolError,
  ToolError,
  isCheckpointConflict,
} from "@arious-meet/mcp";
import { modeFetch, push, startMock, stopMock, token } from "./helpers.js";

let url = "";
let base = "";
before(async () => {
  url = await startMock();
  base = url.replace("/v1/mcp", "");
});
after(stopMock);

const mk = (tok: string, mode = "json", extra: Record<string, unknown> = {}) =>
  new AriousClient({ token: tok, url, modelName: "Test Model", backoffMs: 5, fetch: modeFetch(mode), ...extra });

const control = (path: string, body: unknown) => fetch(base + path, { method: "POST", body: JSON.stringify(body) });
const create = async (c: AriousClient, title = "Ship 0.3", goal = "Release the SDK") =>
  (await c.contextCreate({ title, goal })).data as any;
const idOf = (created: any): string => created.context.id;

describe("Arious Context", () => {
  for (const mode of ["json", "sse"]) {
    it(`resume where another agent left off (${mode})`, async () => {
      const tok = token();
      const writer = mk(tok, mode, { modelName: "Agent A" });
      const cid = idOf(await create(writer));
      const first = (
        await writer.contextCheckpoint({
          context_id: cid,
          base_version: 1,
          current_step: "Writing tests",
          append: { done_steps: ["Spec read"], next_steps: ["Run the suite"] },
        })
      ).data;
      assert.equal(first.version, 2);
      assert.deepEqual(first.redacted, []);

      const reader = mk(tok, mode, { modelName: "Agent B" });
      const resume = (await reader.contextResume()).data; // newest active context
      assert.equal(resume.context_id, cid);
      assert.equal(resume.version, 2);
      assert.equal(resume.can_write, true);
      assert.equal(resume.scope, "personal");
      assert.match(resume.brief, /Where we are now: Writing tests/);
      assert.match(resume.brief, /Next step: Run the suite/);
      const next = (
        await reader.contextCheckpoint({
          context_id: cid,
          base_version: resume.version,
          append: { done_steps: ["Suite green"] },
        })
      ).data;
      assert.equal(next.version, 3);
      const got = (await reader.contextGet({ context_id: cid, history: 2 })).data;
      assert.equal(got.version.author.model, "Agent B");
      assert.deepEqual(got.version.done_steps, ["Spec read", "Suite green"]);
      assert.deepEqual(
        got.history.map((h: any) => h.version),
        [3, 2],
      );
    });
  }

  it("checkpoint redacts secrets and reports them", async () => {
    const c = mk(token());
    const cid = idOf(await create(c));
    const res = (
      await c.contextCheckpoint({
        context_id: cid,
        base_version: 1,
        notes: "use sk-abcdefghijklmnopqrstuvwxyz and password=hunter2 here",
      })
    ).data;
    const kinds = Object.fromEntries(res.redacted.map((r) => [`${r.field}/${r.kind}`, r.count]));
    assert.deepEqual(kinds, { "notes/api_key": 1, "notes/secret_value": 1 });
    const stored = ((await c.contextGet({ context_id: cid })).data as any).version;
    assert.ok(!stored.notes.includes("hunter2"));
    assert.match(stored.notes, /\[REDACTED:api_key\]/);
  });

  it("a lost race throws ContextConflict carrying the latest version", async () => {
    const tok = token();
    const c = mk(tok);
    const cid = idOf(await create(c));
    await control("/__mock/context_write", { token: tok, context_id: cid, current_step: "elsewhere", model: "Other" });
    await assert.rejects(
      c.contextCheckpoint({ context_id: cid, base_version: 1, current_step: "mine" }),
      (e: unknown) => {
        assert.ok(e instanceof ContextConflict);
        assert.ok(e instanceof ToolError); // old handlers keep working
        assert.equal(e.baseVersion, 1);
        assert.equal(e.latestVersion, 2);
        assert.equal(e.latest?.current_step, "elsewhere");
        assert.equal(e.latest?.author.model, "Other");
        return true;
      },
    );
    const ok = await c.contextCheckpoint({ context_id: cid, base_version: 2, current_step: "mine" });
    assert.equal(ok.data.version, 3);
  });

  it("conflict as a result with throwOnToolError: false", async () => {
    const tok = token();
    const c = mk(tok, "json", { throwOnToolError: false });
    const cid = idOf(await create(c));
    await control("/__mock/context_write", { token: tok, context_id: cid });
    const res = await c.contextCheckpoint({ context_id: cid, base_version: 1, current_step: "mine" });
    assert.equal(res.isError, true);
    assert.ok(isCheckpointConflict(res.data));
    const conflict = res.data as unknown as CheckpointConflict;
    assert.equal(conflict.latest_version, 2);
    assert.equal(conflict.latest?.version, 2);
  });

  it("other tool errors stay plain ToolErrors", async () => {
    const c = mk(token());
    await assert.rejects(c.contextGet({ context_id: "nope" }), (e: unknown) => {
      assert.ok(e instanceof ToolError && !(e instanceof ContextConflict));
      assert.match((e as Error).message, /not found/);
      return true;
    });
    await assert.rejects(c.contextResume(), /no active context/);
  });

  it("list, search, status and validation", async () => {
    const c = mk(token());
    const a = idOf(await create(c, "Alpha plan", "first goal"));
    const b = idOf(await create(c, "Beta plan", "second goal"));
    const all = ((await c.contextList()).data as any).contexts.map((x: any) => x.id);
    assert.deepEqual(new Set(all), new Set([a, b]));
    await c.contextSetStatus({ context_id: a, status: "paused" });
    assert.deepEqual(
      ((await c.contextList({ status: "paused" })).data as any).contexts.map((x: any) => x.id),
      [a],
    );
    assert.deepEqual(
      ((await c.contextSearch({ query: "second" })).data as any).contexts.map((x: any) => x.id),
      [b],
    );
    await assert.rejects(c.contextCheckpoint({ context_id: a, base_version: -1 }), ToolError);
  });

  it("context off is a ToolError with the reason", async () => {
    const tok = token();
    const c = mk(tok);
    await control("/__mock/contexts", { token: tok, enabled: false });
    await assert.rejects(c.contextList(), (e: unknown) => {
      assert.ok(e instanceof ToolError);
      assert.deepEqual((e.result as any).structured, { contexts_enabled: false, reason: "turned_off_by_owner" });
      return true;
    });
    assert.equal((await c.startHere()).data.last_context.enabled, false);
    await control("/__mock/contexts", { token: tok, enabled: true });
    assert.deepEqual(((await c.contextList()).data as any).contexts, []);
  });

  it("organization scope and classification", async () => {
    const c = mk(token());
    const personal = idOf(await create(c, "Mine"));
    const org = (
      await c.contextCreate({
        title: "Board pack",
        goal: "g",
        organization_id: "org-1",
        classification: "confidential",
      })
    ).data as any;
    assert.equal(org.context.scope, "organization");
    assert.equal(org.context.classification, "confidential");
    assert.deepEqual(
      ((await c.contextList()).data as any).contexts.map((x: any) => x.id),
      [personal],
    );
    const listed = (await c.contextList({ organization_id: "org-1" })).data as any;
    assert.equal(listed.scope, "organization");
    assert.deepEqual(
      listed.contexts.map((x: any) => x.id),
      [org.context.id],
    );
    const res = (await c.contextResume({ context_id: org.context.id, organization_id: "org-1" })).data;
    assert.equal(res.scope, "organization");
    assert.equal(res.organization_id, "org-1");
    assert.equal(res.classification, "confidential");
    await assert.rejects(
      c.contextCreate({ title: "S", organization_id: "org-1", classification: "secret" }),
      /clearance/,
    );
    await assert.rejects(c.contextList({ organization_id: "org-9" }), /organization not found/);
    assert.ok(
      (await c.contextResume({ context_id: org.context.id, organization_id: "org-1", conversation_id: "conv-1" })).data,
    );
  });

  it("startHere is typed and platform updates are acknowledged by id", async () => {
    const c = mk(token());
    const cid = idOf(await create(c, "Resume me", "goal"));
    const s = (await c.startHere()).data;
    assert.equal(s.identity.name, "Mock Agent");
    assert.equal(s.last_context.enabled, true);
    assert.equal(s.last_context.context_id, cid);
    assert.match(s.last_context.brief ?? "", /Resume me/);
    assert.equal(s.platform_updates.unread_count, 2);
    const important = s.platform_updates.items.filter((u) => u.importance === "important").map((u) => u.id);
    assert.deepEqual(important, ["upd-context"]);
    assert.equal(s.conversations[0]?.id, "conv-1");
    assert.ok(s.house_rules.length > 0 && s.do_now.length > 0);
    assert.match((await c.startHere()).text, /^START HERE/);
    await c.ackUpdates({ update_ids: important });
    assert.equal(
      (await c.startHere()).data.platform_updates.items.filter((u) => u.importance === "important").length,
      0,
    );
    await assert.rejects(c.ackUpdates({}), ToolError);
  });

  it("prompts: list and get", async () => {
    const c = mk(token());
    const prompts = await c.listPrompts();
    assert.deepEqual(prompts.map((p) => p.name).sort(), ["resume", "start"]);
    const resume = prompts.find((p) => p.name === "resume");
    assert.deepEqual(
      resume?.arguments?.map((a) => [a.name, a.required]),
      [
        ["context_id", false],
        ["organization_id", false],
      ],
    );
    const cid = idOf(await create(c, "Prompted", "g"));
    const res = await c.getPrompt("resume", { context_id: cid });
    assert.equal(res.messages[0]?.role, "user");
    assert.match(res.text, /Title: Prompted/);
    assert.match((await c.getPrompt("start")).text, /START HERE/);
    await assert.rejects(c.getPrompt("nope"), (e: unknown) => e instanceof ProtocolError && e.code === -32602);
  });

  it("contextReminder and platform_update items", async () => {
    const tok = token();
    const c = mk(tok);
    await push(url, tok, [
      { kind: "message", conversation_id: "c1", message_id: "m1", text: "hi" },
      { kind: "platform_update", id: "upd-x", title: "New", importance: "important" },
    ]);
    const res = await c.getUpdates();
    assert.match(res.contextReminder ?? "", /context_checkpoint/);
    const items = (res.data as any).updates.filter((u: any) => u.kind === "platform_update");
    assert.deepEqual(
      items.map((u: any) => u.id),
      ["upd-x"],
    );
    assert.ok((await c.readMessages({ conversation_id: "c1" })).contextReminder);
    assert.ok((await c.getMessage({ conversation_id: "c1", message_id: "m1" })).contextReminder);
    assert.equal((await c.readMessages({ conversation_id: "empty" })).contextReminder, null);
    await control("/__mock/contexts", { token: tok, enabled: false });
    assert.equal((await c.getUpdates()).contextReminder, null);
  });
});
