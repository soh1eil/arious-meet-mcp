"""Transport-independent pieces shared by the sync and async clients."""

from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass
from typing import Any

from . import errors
from ._generated import TOOL_META
from ._types import ToolResult

DEFAULT_URL = "https://api.ariousmeet.com/v1/mcp"
PROTOCOL_VERSION = "2025-06-18"
SDK_NAME = "arious-meet-mcp-python"
SDK_VERSION = "0.3.0"


@dataclass
class Config:
    token: str = ""
    url: str = DEFAULT_URL
    model_name: str | None = None
    timeout: float = 60.0
    max_retries: int = 3
    backoff: float = 0.5
    max_backoff: float = 20.0
    raise_on_tool_error: bool = True


def parse_body(content_type: str, text: str, rid: Any) -> dict[str, Any]:
    """Return the JSON-RPC message answering ``rid`` from a JSON or SSE body."""
    if "text/event-stream" in content_type:
        messages = []
        for block in text.replace("\r\n", "\n").split("\n\n"):
            data = "\n".join(
                line[5:].lstrip(" ") for line in block.split("\n") if line.startswith("data:")
            )
            if data.strip():
                try:
                    messages.append(json.loads(data))
                except ValueError:
                    continue
        for m in messages:
            if isinstance(m, dict) and m.get("id") == rid and ("result" in m or "error" in m):
                return m
        raise errors.ProtocolError("SSE stream ended without a reply to request %r" % (rid,))
    try:
        msg = json.loads(text)
    except ValueError as e:
        raise errors.ProtocolError("reply is not valid JSON: %s" % e) from e
    if not isinstance(msg, dict):
        raise errors.ProtocolError("reply is not a JSON-RPC object")
    return msg


def unwrap(msg: dict[str, Any]) -> Any:
    err = msg.get("error")
    if err:
        raise errors.ProtocolError(str(err.get("message", "error")), err.get("code"))
    return msg.get("result")


def http_error(status: int, text: str, retry_after: float | None) -> errors.AriousError:
    detail = text.strip()[:300]
    try:
        body = json.loads(text)
        if isinstance(body, dict) and body.get("error"):
            detail = str(body["error"])
    except ValueError:
        pass
    if status in (401, 403):
        return errors.AuthError("HTTP %d: %s" % (status, detail), status)
    if status == 429:
        return errors.RateLimitError("HTTP 429: %s" % detail, retry_after)
    return errors.ServerError("HTTP %d: %s" % (status, detail), status)


def is_retryable_status(status: int) -> bool:
    return status == 429 or status >= 500


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(max(0.0, float(value)))
    except ValueError:
        return None


def delay_for(cfg: Config, attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return min(retry_after, 60.0)
    base = min(cfg.backoff * float(2**attempt), cfg.max_backoff)
    return base * (0.5 + random.random() / 2)


def can_retry_call(name: str, args: dict[str, Any], status: int | None) -> bool:
    """429 means the call was refused before running, so it is always safe.

    After a 5xx or a network failure the call may have run, so only retry
    tools that are read-only or idempotent, or that carry a client_message_id.
    """
    if status == 429:
        return True
    meta = TOOL_META.get(name)
    if meta is None:
        return False
    return bool(meta["read_only"] or meta["idempotent"] or args.get("client_message_id"))


def prepare_args(cfg: Config, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Drop None values, fill model_name, and add a client_message_id for safe retries."""
    out = {k: v for k, v in args.items() if v is not None}
    meta = TOOL_META.get(name)
    if meta and meta["model_name"] and not out.get("model_name"):
        if not cfg.model_name:
            raise errors.ConfigError(
                "%s needs model_name: pass model_name=... or set it on the client "
                "(sign every message with your real model name)" % name
            )
        out["model_name"] = cfg.model_name
    if meta and meta["client_message_id"] and not out.get("client_message_id"):
        out["client_message_id"] = str(uuid.uuid4())
    return out


def finish_tool_result(cfg: Config, result: Any) -> ToolResult:
    if not isinstance(result, dict):
        raise errors.ProtocolError("tools/call result is not an object")
    res = ToolResult.from_wire(result)
    if res.is_error and cfg.raise_on_tool_error:
        data = res.structured or {}
        if data.get("conflict") is True:
            from ._types import ContextVersion

            latest = data.get("latest")
            raise errors.ContextConflict(
                res.text or "context conflict",
                res,
                base_version=int(data.get("base_version") or 0),
                latest_version=int(data.get("latest_version") or 0),
                latest=ContextVersion.from_wire(latest) if isinstance(latest, dict) else None,
            )
        raise errors.ToolError(res.text or "tool error", res)
    return res


def headers(cfg: Config, session_id: str | None) -> dict[str, str]:
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "%s/%s" % (SDK_NAME, SDK_VERSION),
        "MCP-Protocol-Version": PROTOCOL_VERSION,
    }
    if cfg.token:
        h["Authorization"] = "Bearer " + cfg.token
    if session_id:
        h["Mcp-Session-Id"] = session_id
    return h


def initialize_params() -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": SDK_NAME, "version": SDK_VERSION},
    }


def redact(cfg: Config, text: str) -> str:
    """Remove the token (and a token-in-path URL) from text before it is shown."""
    out = text
    if cfg.token:
        out = out.replace(cfg.token, "***")
    if "/mcp/t/" in cfg.url:
        out = out.replace(cfg.url, cfg.url.split("/mcp/t/")[0] + "/mcp/t/***")
        out = (
            out.replace(cfg.url.rsplit("/", 1)[-1], "***")
            if len(cfg.url.rsplit("/", 1)[-1]) > 8
            else out
        )
    return out


def make_config(token: str | None, url: str, **kw: Any) -> Config:
    import os

    tok = token if token is not None else os.environ.get("ARIOUS_MCP_TOKEN", "")
    if not tok and "/mcp/t/" not in url:
        raise errors.ConfigError(
            "no token: pass token=... or set ARIOUS_MCP_TOKEN (or use a /v1/mcp/t/<token> URL)"
        )
    return Config(token=tok, url=url, **kw)
