"""Synchronous client (httpx)."""

from __future__ import annotations

import io
import mimetypes
import os
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any, BinaryIO

import httpx

from . import _core as core
from . import errors
from ._generated import ToolsMixin
from ._types import ToolResult

Tool = dict[str, Any]


class Client(ToolsMixin):
    """Blocking MCP client for Arious Meet.

    >>> client = Client(token="...", model_name="Claude Sonnet 5")
    >>> client.whoami().data
    """

    def __init__(
        self,
        token: str | None = None,
        *,
        url: str = core.DEFAULT_URL,
        model_name: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff: float = 0.5,
        raise_on_tool_error: bool = True,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._cfg = core.make_config(
            token,
            url,
            model_name=model_name,
            timeout=timeout,
            max_retries=max_retries,
            backoff=backoff,
            raise_on_tool_error=raise_on_tool_error,
        )
        self._http = http_client or httpx.Client(timeout=timeout)
        self._owns_http = http_client is None
        self._session_id: str | None = None
        self._initialized = False
        self._lock = threading.Lock()
        self._init_lock = threading.Lock()
        self._next_id = 0
        self.server_info: dict[str, Any] = {}

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def model_name(self) -> str | None:
        return self._cfg.model_name

    @model_name.setter
    def model_name(self, value: str | None) -> None:
        self._cfg.model_name = value

    # -- transport ---------------------------------------------------------
    def _post(self, payload: dict[str, Any], *, retry_ok: Callable[[int | None], bool]) -> Any:
        """POST one JSON-RPC message with retries. Returns the parsed reply (or None for 202)."""
        cfg = self._cfg
        attempt = 0
        while True:
            status: int | None = None
            retry_after: float | None = None
            try:
                resp = self._http.post(
                    cfg.url,
                    json=payload,
                    headers=core.headers(cfg, self._session_id),
                    timeout=cfg.timeout,
                )
                status = resp.status_code
                retry_after = core.parse_retry_after(resp.headers.get("Retry-After"))
                if status < 400:
                    sid = resp.headers.get("Mcp-Session-Id")
                    if sid and payload.get("method") == "initialize":
                        self._session_id = sid
                    if status == 202 or not resp.content:
                        return None
                    msg = core.parse_body(
                        resp.headers.get("Content-Type", ""), resp.text, payload.get("id")
                    )
                    return msg
                failure: errors.AriousError = core.http_error(status, resp.text, retry_after)
            except httpx.HTTPError as e:
                failure = errors.TransportError(
                    "%s: %s" % (type(e).__name__, core.redact(cfg, str(e)))
                )
            if (
                isinstance(failure, errors.AuthError)
                or not (status is None or core.is_retryable_status(status))
                or attempt >= cfg.max_retries
                or not retry_ok(status)
            ):
                raise failure
            time.sleep(core.delay_for(cfg, attempt, retry_after))
            attempt += 1

    def _rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        retry_ok: Callable[[int | None], bool] = lambda s: True,
    ) -> Any:
        with self._lock:
            self._next_id += 1
            rid = self._next_id
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            payload["params"] = params
        msg = self._post(payload, retry_ok=retry_ok)
        return core.unwrap(msg) if msg is not None else None

    def initialize(self) -> dict[str, Any]:
        """Run the initialize handshake (done automatically on first use)."""
        result = self._rpc("initialize", core.initialize_params())
        self.server_info = result.get("serverInfo", {}) if isinstance(result, dict) else {}
        self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}, retry_ok=lambda s: True
        )
        self._initialized = True
        return result if isinstance(result, dict) else {}

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            with self._init_lock:
                if not self._initialized:
                    self.initialize()

    # -- protocol ----------------------------------------------------------
    def list_tools(self) -> list[Tool]:
        self._ensure_initialized()
        result = self._rpc("tools/list")
        return list((result or {}).get("tools", []))

    def ping(self) -> None:
        self._ensure_initialized()
        self._rpc("ping")

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        """Call any tool by name. Raises ToolError if the server sets isError."""
        args = core.prepare_args(self._cfg, name, arguments or {})
        self._ensure_initialized()
        result = self._rpc(
            "tools/call",
            {"name": name, "arguments": args},
            retry_ok=lambda s: core.can_retry_call(name, args, s),
        )
        return core.finish_tool_result(self._cfg, result)

    def _call_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        return self.call_tool(name, args)

    # -- helpers -----------------------------------------------------------
    def watch_updates(
        self,
        *,
        only: list[str] | None = None,
        wait_seconds: int = 25,
        ack: bool = True,
        max_text_chars: int | None = None,
        stop: Callable[[], bool] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Long-poll get_updates forever, yielding each update dict.

        After the consumer has processed a whole batch (the generator is
        resumed past its last item) the batch cursor is acknowledged with
        ack_updates, so a crash replays the batch instead of losing it.
        Transient failures (rate limit, 5xx, network) are retried with
        backoff; AuthError and ToolError propagate. Stop by breaking out of
        the loop or by making ``stop()`` return True.
        """
        cursor: str | None = None
        failures = 0
        while not (stop and stop()):
            try:
                res = self.get_updates(
                    cursor=cursor,
                    wait_seconds=wait_seconds,
                    only=only,
                    max_text_chars=max_text_chars,
                )
            except (errors.RateLimitError, errors.ServerError, errors.TransportError):
                failures += 1
                time.sleep(core.delay_for(self._cfg, min(failures, 6), None))
                continue
            failures = 0
            data = res.data if isinstance(res.data, dict) else {}
            updates = data.get("updates") or []
            nxt = data.get("next_cursor")
            yield from updates
            if nxt:
                cursor = nxt
                if ack and updates:
                    self.ack_updates(cursor=nxt)

    def upload_and_send(
        self,
        conversation_id: str,
        file: str | os.PathLike[str] | bytes | BinaryIO,
        *,
        filename: str | None = None,
        mime: str | None = None,
        caption: str | None = None,
        send: bool = True,
        **send_kwargs: Any,
    ) -> ToolResult:
        """create_upload_url, PUT the bytes, then send_file. Returns send_file's result.

        With ``send=False`` stops after the upload and returns the
        create_upload_url result (its ``data["upload_id"]`` can go to any tool).
        Extra keyword arguments (reply_to_id, silent, as_voice...) go to send_file.
        """
        if isinstance(file, (str, os.PathLike)):
            path = os.fspath(file)
            filename = filename or os.path.basename(path)
            size = os.path.getsize(path)
            owned = True
            opener: Callable[[], BinaryIO] = lambda: open(path, "rb")  # noqa: E731
        elif isinstance(file, bytes):
            if not filename:
                raise errors.ConfigError("filename is required when uploading bytes")
            size = len(file)
            data = file
            owned = False
            opener = lambda: io.BytesIO(data)  # noqa: E731
        else:
            if not filename:
                raise errors.ConfigError("filename is required when uploading a file object")
            file.seek(0, os.SEEK_END)
            size = file.tell()
            owned = False

            def opener() -> BinaryIO:
                file.seek(0)
                return file

        mime = mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        ticket = self.create_upload_url(
            conversation_id=conversation_id, filename=filename, size=size, mime=mime
        )
        info = ticket.data
        self._put_upload(info, opener, owned, size, mime)
        if not send:
            return ticket
        return self.send_file(
            conversation_id=conversation_id,
            upload_id=info["upload_id"],
            caption=caption,
            **send_kwargs,
        )

    def _put_upload(
        self,
        info: dict[str, Any],
        opener: Callable[[], BinaryIO],
        owned: bool,
        size: int,
        mime: str,
    ) -> None:
        cfg = self._cfg
        hdrs = dict(info.get("headers") or {})
        hdrs.setdefault("Content-Type", mime)
        hdrs["Content-Length"] = str(size)
        attempt = 0
        while True:
            status: int | None = None
            try:
                fh = opener()
                try:
                    resp = self._http.put(
                        info["upload_url"], content=fh, headers=hdrs, timeout=cfg.timeout
                    )
                finally:
                    if owned:
                        fh.close()
                status = resp.status_code
                if status < 400:
                    return
                failure: errors.AriousError = core.http_error(status, resp.text, None)
            except httpx.HTTPError as e:
                failure = errors.TransportError("upload failed: %s" % type(e).__name__)
            if (
                isinstance(failure, errors.AuthError)
                or not (status is None or core.is_retryable_status(status))
                or attempt >= cfg.max_retries
            ):
                raise failure
            time.sleep(core.delay_for(cfg, attempt, None))
            attempt += 1
