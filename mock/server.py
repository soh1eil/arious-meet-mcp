#!/usr/bin/env python3
"""Shared mock Arious Meet MCP server for every SDK's test suite.

Stdlib only. See README.md for the contract. Not a faithful copy of the real
server: it implements just enough of the protocol (initialize, tools/list,
tools/call, SSE and JSON replies, 401/429/5xx) to exercise a client.
"""
import argparse
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "..", "spec", "tools.json")
PROTOCOL = "2025-06-18"
KNOWN = {"2025-03-26", "2025-06-18"}
LOCK = threading.Lock()


class State:
    def __init__(self, mode, fail_count):
        self.mode = mode
        self.fail_count = fail_count
        self.reset()

    def reset(self):
        self.calls = {}      # per token: tools/call attempts counted for fail modes
        self.log = []        # every JSON-RPC request seen
        self.messages = {}   # (token, client_message_id) -> message
        self.queue = {}      # token -> list of update items (each has _seq)
        self.acked = {}      # token -> seq
        self.seq = 0
        self.uploads = {}    # upload_id -> bytes
        self.sent = []       # every send_message / send_file / send_gif result
        self.actions = []    # every accepted chat action {conversation_id, action}


S = None


def load_tools():
    with open(SPEC, encoding="utf-8") as f:
        return json.load(f)["tools"]


TOOLS = load_tools()
TOOL_NAMES = {t["name"] for t in TOOLS}


def struct_result(obj, text=None, is_error=False):
    out = {"content": [{"type": "text", "text": text if text is not None else json.dumps(obj)}]}
    if obj is not None:
        out["structuredContent"] = obj
    if is_error:
        out["isError"] = True
    return out


CHAT_ACTIONS = [
    "typing", "upload_photo", "upload_video", "record_voice", "upload_voice",
    "upload_document", "record_video_note", "upload_video_note", "choose_sticker",
    "find_location", "cancel",
]

# A tiny GIF library: (gif_id, title, width, height). Trending = all, in order.
GIF_LIBRARY = [
    ("gif-001", "thumbs up", 480, 270),
    ("gif-002", "celebration confetti", 498, 280),
    ("gif-003", "applause", 400, 300),
    ("gif-004", "facepalm", 480, 360),
    ("gif-005", "thumbs up cat", 320, 320),
    ("gif-006", "mind blown", 480, 270),
]


def tool_error(msg):
    return {"content": [{"type": "text", "text": msg}], "isError": True}


def call_tool(token, name, args, base):
    if name == "whoami":
        return struct_result({"agent_id": "agent-1", "display_name": "Mock Agent", "owner": "mock-owner"})
    if name == "get_handbook":
        sec = args.get("section")
        text = "# Handbook\nsection: %s" % sec if sec else "# Handbook\nfull"
        return {"content": [{"type": "text", "text": text}]}
    if name == "search_app_guide":
        if not args.get("query"):
            return tool_error("query is required")
        return struct_result({"results": [{"title": "Guide", "snippet": args["query"]}]})
    if name == "list_organizations":
        return struct_result({"organizations": [{"id": "org-1", "name": "Mock Org"}]})
    if name == "mock_tool_error":
        return tool_error("this is a tool-level error")
    if name == "mock_protocol_error":
        raise RpcError(-32602, "no such tool: mock_protocol_error")
    if name == "send_message":
        if not args.get("model_name"):
            return tool_error("model_name is required: sign every message with your real model name")
        if not args.get("conversation_id") or "text" not in args:
            return tool_error("conversation_id and text are required")
        with LOCK:
            cid = args.get("client_message_id")
            if cid and (token, cid) in S.messages:
                m = dict(S.messages[(token, cid)])
                m["deduplicated"] = True
                return struct_result(m)
            m = {
                "message_id": "msg-%d" % (len(S.sent) + 1),
                "conversation_id": args["conversation_id"],
                "text": args["text"] + "\n\n" + args["model_name"],
            }
            S.sent.append(m)
            if cid:
                S.messages[(token, cid)] = m
        return struct_result(m)
    if name == "get_updates":
        return get_updates(token, args)
    if name == "ack_updates":
        cur = args.get("cursor")
        if not cur:
            return tool_error("cursor is required")
        with LOCK:
            S.acked[token] = parse_cursor(cur)
        return struct_result({"acked": cur})
    if name == "create_upload_url":
        for k in ("conversation_id", "filename", "size"):
            if k not in args:
                return tool_error("%s is required" % k)
        uid = "up-" + uuid.uuid4().hex[:8]
        return struct_result({
            "upload_url": "%s/v1/agent-uploads/%s" % (base, uid),
            "method": "PUT",
            "headers": {"Content-Type": args.get("mime") or "application/octet-stream"},
            "upload_id": uid,
            "expires_at": "2099-01-01T00:00:00Z",
        })
    if name == "send_file":
        if not args.get("model_name"):
            return tool_error("model_name is required")
        uid = args.get("upload_id")
        with LOCK:
            if uid not in S.uploads:
                return tool_error("upload not found or not uploaded yet")
            m = {"message_id": "msg-file-%d" % (len(S.sent) + 1), "upload_id": uid,
                 "size_bytes": len(S.uploads[uid]), "conversation_id": args.get("conversation_id")}
            S.sent.append(m)
        return struct_result(m)
    if name in ("send_typing", "send_chat_action"):
        if not args.get("conversation_id"):
            return tool_error("conversation_id is required")
        action = args.get("action")
        if name == "send_chat_action" and not action:
            return tool_error("action is required; one of: " + ", ".join(CHAT_ACTIONS))
        if action is None or action == "":
            action = "typing"
        if action not in CHAT_ACTIONS:
            return tool_error("unknown action; one of: " + ", ".join(CHAT_ACTIONS))
        with LOCK:
            S.actions.append({"conversation_id": args["conversation_id"], "action": action})
        return {"content": [{"type": "text", "text": "sent"}]}
    if name == "search_gifs":
        limit = args.get("limit", 10)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 25:
            return tool_error("limit must be between 1 and 25")
        q = (args.get("query") or "").strip().lower()
        rows = [g for g in GIF_LIBRARY if not q or all(w in g[1] for w in q.split())]
        gifs = [{
            "gif_id": g[0], "title": g[1], "width": g[2], "height": g[3],
            "content_type": "image/gif", "source": "library",
            "preview_url": "%s/v1/gifs/agent-preview/%s/4102444800/mocksig" % (base, g[0]),
        } for g in rows[:limit]]
        out = {"gifs": gifs}
        text = "%d GIF(s). Send one with send_gif(gif_id)." % len(gifs)
        if q == "busy":
            out["busy"] = True
            text += " The live GIF source is busy, so this list may be shorter than usual; try again later for more."
        return struct_result(out, text)
    if name == "send_gif":
        if not args.get("model_name"):
            return tool_error("model_name is required: sign every message with your real model name")
        if not (args.get("conversation_id") or "").strip():
            return tool_error("conversation_id is required")
        gid = (args.get("gif_id") or "").strip()
        if not gid:
            return tool_error("gif_id is required")
        if gid not in [g[0] for g in GIF_LIBRARY]:
            return tool_error("that GIF is not in the library; find one with search_gifs")
        cap = args.get("caption") or ""
        if len(cap) > 3000:
            return tool_error("caption is too long")
        with LOCK:
            n = len(S.sent) + 1
            m = {"message_id": "msg-gif-%d" % n, "conversation_id": args["conversation_id"],
                 "attachment_id": "att-gif-%d" % n, "gif_id": gid}
            if args.get("silent"):
                m["silent"] = True
            S.sent.append(dict(m, caption=cap, reply_to_id=args.get("reply_to_id"),
                               topic_id=args.get("topic_id")))
        return struct_result(m, "sent")
    if name in TOOL_NAMES:
        return tool_error("tool %s is not implemented by the mock server" % name)
    raise RpcError(-32602, "no such tool: " + name)


def parse_cursor(c):
    try:
        return int(str(c).lstrip("c"))
    except ValueError:
        return 0


def get_updates(token, args):
    wait = min(int(args.get("wait_seconds") or 0), 3)
    deadline = time.time() + wait
    while True:
        with LOCK:
            cur = parse_cursor(args["cursor"]) if args.get("cursor") else S.acked.get(token, 0)
            items = [dict((k, v) for k, v in i.items() if k != "_seq")
                     for i in S.queue.get(token, []) if i["_seq"] > cur]
            raw = [i for i in S.queue.get(token, []) if i["_seq"] > cur]
            only = args.get("only")
            if only:
                keep = [(r, i) for r, i in zip(raw, items) if i.get("kind") in only]
                raw = [r for r, _ in keep]
                items = [i for _, i in keep]
            nxt = max([r["_seq"] for r in raw] + [cur])
            if items or time.time() >= deadline:
                if args.get("ack"):
                    S.acked[token] = nxt
                return struct_result({"updates": items, "next_cursor": "c%d" % nxt})
        time.sleep(0.05)


class RpcError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "arious-mock/1"

    def log_message(self, *a):
        pass

    # -- helpers -----------------------------------------------------------
    def _token(self):
        p = urlparse(self.path).path
        if p.startswith("/v1/mcp/t/"):
            return p[len("/v1/mcp/t/"):].strip("/")
        a = self.headers.get("Authorization", "")
        if a.lower().startswith("bearer "):
            return a[7:].strip()
        return self.headers.get("X-API-Key", "").strip()

    def _send(self, status, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _base(self):
        return "http://%s" % self.headers.get("Host", "127.0.0.1")

    def _mode(self):
        return self.headers.get("X-Mock-Mode") or S.mode

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    # -- routes ------------------------------------------------------------
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/__mock/log":
            return self._send(200, {"log": S.log, "sent": S.sent, "actions": S.actions})
        if not (u.path == "/v1/mcp" or u.path.startswith("/v1/mcp/t/")):
            return self._send(404, {"error": "not found"})
        tok = self._token()
        if not tok.startswith("test-"):
            return self._send(401, {"error": "unauthorised"})
        if "text/event-stream" not in self.headers.get("Accept", ""):
            return self._send(406, {"error": "Accept: text/event-stream required"})
        # Server->client stream: one notification per queued update that is
        # newer than the acked cursor, a keep-alive comment, then close after
        # ?hold= seconds (default 0.3).
        hold = float(parse_qs(u.query).get("hold", ["0.3"])[0])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Mcp-Session-Id", "sess-" + uuid.uuid4().hex[:6])
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        w = self.wfile
        w.write(b": keep-alive\n\n")
        w.flush()
        end = time.time() + hold
        seen = 0
        while time.time() < end:
            with LOCK:
                new = [i for i in S.queue.get(tok, []) if i["_seq"] > seen]
            for i in new:
                seen = max(seen, i["_seq"])
                meta = {k: v for k, v in i.items() if k != "_seq"}
                ev = {"jsonrpc": "2.0", "method": "notifications/resources/updated",
                      "params": {"uri": "arious://updates", "_meta": {"arious/inbox": meta}}}
                w.write(("data: %s\n\n" % json.dumps(ev)).encode())
                w.flush()
            time.sleep(0.05)

    def do_DELETE(self):
        self._send(204, b"", extra={})

    def do_PUT(self):
        u = urlparse(self.path)
        if u.path.startswith("/v1/agent-uploads/"):
            uid = u.path.rsplit("/", 1)[1]
            data = self._body()
            with LOCK:
                S.uploads[uid] = data
            return self._send(200, {"ok": True, "size": len(data)})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path.startswith("/__mock/"):
            return self._control(u.path)
        if not (u.path == "/v1/mcp" or u.path.startswith("/v1/mcp/t/")):
            return self._send(404, {"error": "not found"})
        raw = self._body()
        tok = self._token()
        if not tok.startswith("test-"):
            return self._send(401, {"error": "unauthorised"},
                              extra={"WWW-Authenticate": 'Bearer realm="mock"'})
        try:
            req = json.loads(raw)
        except ValueError:
            return self._rpc(None, error=(-32700, "parse error"))
        with LOCK:
            S.log.append({"method": req.get("method"), "params": req.get("params"), "token": tok[:8]})
        method, rid = req.get("method"), req.get("id")
        if method == "notifications/initialized":
            return self._send(202, b"", extra={})
        if method == "initialize":
            pv = (req.get("params") or {}).get("protocolVersion")
            return self._rpc(rid, result={
                "protocolVersion": pv if pv in KNOWN else PROTOCOL,
                "capabilities": {"tools": {}, "resources": {"subscribe": True}},
                "serverInfo": {"name": "arious-agents", "title": "Arious Meet (mock)", "version": "mock"},
                "instructions": "mock server",
            }, extra={"Mcp-Session-Id": "sess-" + uuid.uuid4().hex[:6]})
        if method == "ping":
            return self._rpc(rid, result={})
        if method == "tools/list":
            return self._rpc(rid, result={"tools": TOOLS})
        if method in ("resources/list",):
            return self._rpc(rid, result={"resources": [
                {"uri": "arious://handbook", "name": "Agent handbook", "mimeType": "text/markdown"},
                {"uri": "arious://updates", "name": "Updates"}]})
        if method in ("resources/subscribe", "resources/unsubscribe"):
            return self._rpc(rid, result={})
        if method == "tools/call":
            mode = self._mode()
            if mode in ("error", "ratelimit"):
                with LOCK:
                    n = S.calls.get(tok, 0)
                    S.calls[tok] = n + 1
                if S.fail_count < 0 or n < S.fail_count:
                    if mode == "ratelimit":
                        return self._send(429, {"error": "too many requests"},
                                          extra={"Retry-After": "0"})
                    return self._send(500, {"error": "internal error"})
            p = req.get("params") or {}
            try:
                res = call_tool(tok, p.get("name"), p.get("arguments") or {}, self._base())
            except RpcError as e:
                return self._rpc(rid, error=(e.code, e.message))
            return self._rpc(rid, result=res)
        return self._rpc(rid, error=(-32601, "method not found: %s" % method))

    def _rpc(self, rid, result=None, error=None, extra=None):
        body = {"jsonrpc": "2.0", "id": rid}
        if error:
            body["error"] = {"code": error[0], "message": error[1]}
        else:
            body["result"] = result
        if self._mode() == "sse":
            payload = ": keep-alive\n\ndata: %s\n\n" % json.dumps(body)
            return self._send(200, payload.encode(), ctype="text/event-stream", extra=extra)
        self._send(200, body, extra=extra)

    def _control(self, path):
        data = json.loads(self._body() or b"{}")
        if path == "/__mock/mode":
            S.mode = data.get("mode", "json")
            if "fail_count" in data:
                S.fail_count = int(data["fail_count"])
            with LOCK:
                S.calls = {}
        elif path == "/__mock/reset":
            with LOCK:
                S.reset()
        elif path == "/__mock/push":
            tok = data.get("token", "")
            with LOCK:
                for it in data.get("items", []):
                    S.seq += 1
                    it = dict(it)
                    it["_seq"] = S.seq
                    S.queue.setdefault(tok, []).append(it)
        else:
            return self._send(404, {"error": "unknown control"})
        self._send(200, {"ok": True, "mode": S.mode})


def main(argv=None):
    global S
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--mode", choices=["json", "sse", "error", "ratelimit"], default="json")
    ap.add_argument("--fail-count", type=int, default=2,
                    help="error/ratelimit modes: tools/call attempts per token that fail "
                         "before succeeding (-1 = always fail)")
    a = ap.parse_args(argv)
    S = State(a.mode, a.fail_count)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    # First stdout line is machine-readable so test harnesses can find the port.
    print("LISTENING http://%s:%d/v1/mcp" % (a.host, srv.server_address[1]), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
