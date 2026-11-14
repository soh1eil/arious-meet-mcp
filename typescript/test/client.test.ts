import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import {
  AriousClient,
  AuthError,
  ChatAction,
  ConfigError,
  ProtocolError,
  RateLimitError,
  ServerError,
  ToolError,
  TransportError,
} from "@arious-meet/mcp";
import { modeFetch, push, startMock, stopMock, token } from "./helpers.js";

let url = "";
before(async () => {
  url = await startMock();
});
after(stopMock);

const mk = (tok: string, mode = "json", extra: Record<string, unknown> = {}) =>
  new AriousClient({
    token: tok,
    url,
    modelName: "Test Model",
    backoffMs: 5,
    fetch: modeFetch(mode),
    ...extra,
  });

describe("client", () => {
  for (const mode of ["json", "sse"]) {
    it(`handshake, list and typed calls (${mode})`, async () => {
      const c = mk(token(), mode);
      assert.equal((await c.listTools()).length, 127);
      assert.equal(c.serverInfo.name, "arious-agents");
      assert.equal((await c.whoami()).data.display_name, "Mock Agent");
      assert.equal((await c.listOrganizations()).data.organizations[0].id, "org-1");
      assert.match((await c.getHandbook()).text, /^# Handbook/);
      assert.match((await c.getHandbook({ section: "formatting" })).text, /formatting/);
      assert.ok((await c.searchAppGuide({ query: "calls" })).data.results.length);
    });
  }

  it("token-in-path form", async () => {
    const c = new AriousClient({ url: `${url}/t/${token()}`, backoffMs: 5 });
    assert.equal((await c.whoami()).data.agent_id, "agent-1");
  });

  it("auth error is not retried and hides the token", async () => {
    const c = mk("wrong-token-xyz");
    await assert.rejects(c.whoami(), (e: unknown) => {
      assert.ok(e instanceof AuthError);
      assert.equal(e.status, 401);
      assert.ok(!String(e.message).includes("wrong-token-xyz"));
      return true;
    });
  });

  it("config errors", async () => {
    const saved = process.env.ARIOUS_MCP_TOKEN;
    delete process.env.ARIOUS_MCP_TOKEN;
    assert.throws(() => new AriousClient({ url }), ConfigError);
    if (saved) process.env.ARIOUS_MCP_TOKEN = saved;
    const c = new AriousClient({ token: "x", url: "http://127.0.0.1:1" });
    await assert.rejects(c.sendMessage({ conversation_id: "c", text: "t" }), ConfigError);
  });

  it("tool error and protocol error", async () => {
    const c = mk(token());
    await assert.rejects(
      c.callTool("mock_tool_error"),
      (e: unknown) => e instanceof ToolError && /tool-level/.test(e.message),
    );
    await assert.rejects(
      c.callTool("mock_protocol_error"),
      (e: unknown) => e instanceof ProtocolError && e.code === -32602,
    );
    await assert.rejects(c.callTool("does_not_exist"), ProtocolError);
    const soft = mk(token(), "json", { throwOnToolError: false });
    const r = await soft.callTool("mock_tool_error");
    assert.ok(r.isError && /tool-level/.test(r.text));
    await assert.rejects(c.callTool("search_app_guide", {}), ToolError);
  });

  it("retries 5xx and 429, then gives up", async () => {
    assert.equal((await mk(token(), "error").whoami()).data.agent_id, "agent-1");
    assert.equal((await mk(token(), "ratelimit").whoami()).data.agent_id, "agent-1");
    await assert.rejects(mk(token(), "error", { maxRetries: 1 }).whoami(), ServerError);
    await assert.rejects(
      mk(token(), "ratelimit", { maxRetries: 0 }).whoami(),
      (e: unknown) => e instanceof RateLimitError && e.retryAfter === 0,
    );
  });

  it("non-idempotent calls are not retried on 5xx, but are on 429", async () => {
    await assert.rejects(
      mk(token(), "error").createUploadUrl({
        conversation_id: "c",
        filename: "a",
        size: 1,
      }),
      ServerError,
    );
    assert.ok(
      (
        await mk(token(), "ratelimit").createUploadUrl({
          conversation_id: "c",
          filename: "a",
          size: 1,
        })
      ).data.upload_id,
    );
  });

  it("send_message signs, auto client_message_id makes 5xx retry safe, explicit id dedupes", async () => {
    const tok = token();
    const m = await mk(tok, "error").sendMessage({
      conversation_id: "c1",
      text: "hello",
    });
    assert.ok(m.data.text.endsWith("Test Model"));
    const a = await mk(tok).sendMessage({
      conversation_id: "c1",
      text: "hi",
      client_message_id: "fixed-1",
    });
    const b = await mk(tok).sendMessage({
      conversation_id: "c1",
      text: "hi",
      client_message_id: "fixed-1",
    });
    assert.equal(b.data.deduplicated, true);
    assert.equal(a.data.message_id, b.data.message_id);
    assert.ok(
      (
        await mk(tok).sendMessage({
          conversation_id: "c",
          text: "x",
          model_name: "Other",
        })
      ).data.text.endsWith("Other"),
    );
  });

  it("transport errors", async () => {
    const c = new AriousClient({
      token: "t",
      url: "http://127.0.0.1:1/v1/mcp",
      maxRetries: 1,
      backoffMs: 5,
    });
    await assert.rejects(c.whoami(), TransportError);
  });

  it("watchUpdates acks after a consumed batch; breaking mid-batch replays", async () => {
    const tok = token();
    const c = mk(tok);
    await push(url, tok, [
      { kind: "mention", text: "a" },
      { kind: "mention", text: "b" },
    ]);
    const seen: string[] = [];
    for await (const u of c.watchUpdates({ waitSeconds: 0 })) {
      seen.push(u.text);
      if (seen.length === 2) break;
    }
    assert.deepEqual(seen, ["a", "b"]);
    assert.deepEqual(
      (await c.getUpdates()).data.updates.map((u: any) => u.text),
      ["a", "b"],
    );
    const ac = new AbortController();
    const got: string[] = [];
    for await (const u of c.watchUpdates({
      waitSeconds: 0,
      signal: ac.signal,
    })) {
      got.push(u.text);
      if (got.length === 2) {
        await push(url, tok, [{ kind: "mention", text: "c" }]);
      }
      if (got.length === 3) ac.abort();
    }
    assert.deepEqual(got, ["a", "b", "c"]);
    // Resuming past the last item acknowledged the batch, so nothing is left.
    assert.deepEqual((await c.getUpdates()).data.updates, []);
  });

  it("uploadAndSend and uploadAndSendPath", async () => {
    const c = mk(token());
    const r = await c.uploadAndSend("conv", new TextEncoder().encode("hello"), {
      filename: "a.txt",
    });
    assert.equal(r.data.size_bytes, 5);
    const t = await c.uploadAndSend("conv", new Blob(["abc"]), {
      filename: "c.txt",
      send: false,
    });
    assert.match(t.data.upload_id, /^up-/);
    const { writeFileSync, mkdtempSync } = await import("node:fs");
    const { tmpdir } = await import("node:os");
    const { join } = await import("node:path");
    const p = join(mkdtempSync(join(tmpdir(), "ts-sdk-")), "b.bin");
    writeFileSync(p, Buffer.alloc(1000, 1));
    assert.equal((await c.uploadAndSendPath("conv", p, { caption: "x" })).data.size_bytes, 1000);
  });

  async function actionsFor(conv: string): Promise<string[]> {
    const log = (await (await fetch(url.replace("/v1/mcp", "/__mock/log"))).json()) as {
      actions: Array<{ conversation_id: string; action: string }>;
    };
    return log.actions.filter((a) => a.conversation_id === conv).map((a) => a.action);
  }

  for (const mode of ["json", "sse"]) {
    it(`sendChatAction and sendTyping (${mode})`, async () => {
      const c = mk(token(), mode);
      const conv = `conv-act-${mode}`;
      assert.equal(Object.keys(ChatAction).length, 11);
      await c.sendChatAction({ conversation_id: conv, action: ChatAction.UploadPhoto });
      await c.sendChatAction({ conversation_id: conv, action: "cancel" });
      await c.sendTyping({ conversation_id: conv }); // backward compatible: typing
      await c.sendTyping({ conversation_id: conv, action: ChatAction.RecordVoice });
      assert.deepEqual(await actionsFor(conv), ["upload_photo", "cancel", "typing", "record_voice"]);
    });
  }

  it("unknown chat action is a ToolError", async () => {
    const c = mk(token());
    await assert.rejects(
      c.sendChatAction({ conversation_id: "conv-bad", action: "dance" as ChatAction }),
      (e: unknown) => e instanceof ToolError && /unknown action/.test(e.message),
    );
    await assert.rejects(c.callTool("send_chat_action", { conversation_id: "conv-bad" }), ToolError);
  });

  it("searchGifs and sendGif have typed results", async () => {
    const c = mk(token());
    const trending = (await c.searchGifs()).data;
    assert.equal(trending.gifs.length, 6);
    assert.equal(trending.busy, undefined);
    const found = (await c.searchGifs({ query: "thumbs up", limit: 1 })).data;
    assert.deepEqual(
      found.gifs.map((g) => g.gif_id),
      ["gif-001"],
    );
    const g = found.gifs[0];
    assert.equal(g?.width, 480);
    assert.equal(g?.content_type, "image/gif");
    assert.equal(g?.source, "library");
    assert.match(g?.preview_url ?? "", /^http/);
    assert.equal((await c.searchGifs({ query: "busy" })).data.busy, true);
    const sent = (await c.sendGif({ conversation_id: "conv-gif", gif_id: "gif-001", caption: "nice", silent: true }))
      .data;
    assert.equal(sent.gif_id, "gif-001");
    assert.equal(sent.conversation_id, "conv-gif");
    assert.match(sent.message_id, /^msg-gif-/);
    assert.match(sent.attachment_id, /^att-gif-/);
    assert.equal(sent.sent_via_grant_name, undefined);
  });

  it("gif errors", async () => {
    const c = mk(token());
    await assert.rejects(c.searchGifs({ limit: 26 }), ToolError);
    await assert.rejects(c.sendGif({ conversation_id: "c", gif_id: "nope" }), ToolError);
    const noModel = new AriousClient({ token: token(), url, backoffMs: 5 });
    await assert.rejects(noModel.sendGif({ conversation_id: "c", gif_id: "gif-001" }), ConfigError);
  });
});
