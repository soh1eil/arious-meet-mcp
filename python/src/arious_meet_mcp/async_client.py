"""Asynchronous client (httpx.AsyncClient). Mirrors :class:`arious_meet_mcp.Client`."""

from __future__ import annotations

import asyncio
import io
import mimetypes
import os
from collections.abc import AsyncIterator, Callable
from typing import Any, BinaryIO

import httpx

from . import _core as core
from . import errors
from ._generated import AsyncToolsMixin
from ._types import ToolResult

Tool = dict[str, Any]


class AsyncClient(AsyncToolsMixin):
    """asyncio MCP client for Arious Meet.

    >>> async with AsyncClient(token="...", model_name="Claude Sonnet 5") as c:
    ...     (await c.whoami()).data
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
        http_client: httpx.AsyncClient | None = None,
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
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._owns_http = http_client is None
        self._session_id: str | None = None
        self._initialized = False
        self._init_lock: asyncio.Lock | None = None
        self._next_id = 0
        self.server_info: dict[str, Any] = {}

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    @property
    def model_name(self) -> str | None:
        return self._cfg.model_name

    @model_name.setter
    def model_name(self, value: str | None) -> None:
        self._cfg.model_name = value

    async def _post(
        self, payload: dict[str, Any], *, retry_ok: Callable[[int | None], bool]
    ) -> Any:
        cfg = self._cfg
        attempt = 0
        while True:
            status: int | None = None
            retry_after: float | None = None
            try:
                resp = await self._http.post(
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
                    return core.parse_body(
                        resp.headers.get("Content-Type", ""), resp.text, payload.get("id")
                    )
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
            await asyncio.sleep(core.delay_for(cfg, attempt, retry_after))
            attempt += 1

    async def _rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        retry_ok: Callable[[int | None], bool] = lambda s: True,
    ) -> Any:
        self._next_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params
        msg = await self._post(payload, retry_ok=retry_ok)
        return core.unwrap(msg) if msg is not None else None

    async def initialize(self) -> dict[str, Any]:
        """Run the initialize handshake (done automatically on first use)."""
        result = await self._rpc("initialize", core.initialize_params())
        self.server_info = result.get("serverInfo", {}) if isinstance(result, dict) else {}
        await self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}, retry_ok=lambda s: True
        )
        self._initialized = True
        return result if isinstance(result, dict) else {}

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            if self._init_lock is None:
                self._init_lock = asyncio.Lock()
            async with self._init_lock:
                if not self._initialized:
                    await self.initialize()

    async def list_tools(self) -> list[Tool]:
        await self._ensure_initialized()
        result = await self._rpc("tools/list")
        return list((result or {}).get("tools", []))

    async def ping(self) -> None:
        await self._ensure_initialized()
        await self._rpc("ping")

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        """Call any tool by name. Raises ToolError if the server sets isError."""
        args = core.prepare_args(self._cfg, name, arguments or {})
        await self._ensure_initialized()
        result = await self._rpc(
            "tools/call",
            {"name": name, "arguments": args},
            retry_ok=lambda s: core.can_retry_call(name, args, s),
        )
        return core.finish_tool_result(self._cfg, result)

    async def _call_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        return await self.call_tool(name, args)

    async def watch_updates(
        self,
        *,
        only: list[str] | None = None,
        wait_seconds: int = 25,
        ack: bool = True,
        max_text_chars: int | None = None,
        stop: Callable[[], bool] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Async version of :meth:`Client.watch_updates`."""
        cursor: str | None = None
        failures = 0
        while not (stop and stop()):
            try:
                res = await self.get_updates(
                    cursor=cursor,
                    wait_seconds=wait_seconds,
                    only=only,
                    max_text_chars=max_text_chars,
                )
            except (errors.RateLimitError, errors.ServerError, errors.TransportError):
                failures += 1
                await asyncio.sleep(core.delay_for(self._cfg, min(failures, 6), None))
                continue
            failures = 0
            data = res.data if isinstance(res.data, dict) else {}
            updates = data.get("updates") or []
            nxt = data.get("next_cursor")
            for u in updates:
                yield u
            if nxt:
                cursor = nxt
                if ack and updates:
                    await self.ack_updates(cursor=nxt)

    async def upload_and_send(
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
        """Async version of :meth:`Client.upload_and_send`."""
        owned = False
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
            opener = lambda: io.BytesIO(data)  # noqa: E731
        else:
            if not filename:
                raise errors.ConfigError("filename is required when uploading a file object")
            file.seek(0, os.SEEK_END)
            size = file.tell()

            def opener() -> BinaryIO:
                file.seek(0)
                return file

        mime = mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        ticket = await self.create_upload_url(
            conversation_id=conversation_id, filename=filename, size=size, mime=mime
        )
        info = ticket.data
        await self._put_upload(info, opener, owned, size, mime)
        if not send:
            return ticket
        return await self.send_file(
            conversation_id=conversation_id,
            upload_id=info["upload_id"],
            caption=caption,
            **send_kwargs,
        )

    async def _put_upload(
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
        attempt = 0
        while True:
            status: int | None = None
            try:
                fh = opener()
                try:
                    body = fh.read()
                finally:
                    if owned:
                        fh.close()
                resp = await self._http.put(
                    info["upload_url"], content=body, headers=hdrs, timeout=cfg.timeout
                )
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
            await asyncio.sleep(core.delay_for(cfg, attempt, None))
            attempt += 1
