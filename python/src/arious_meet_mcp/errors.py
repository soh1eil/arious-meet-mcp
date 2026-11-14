"""Typed errors. Everything the SDK raises derives from :class:`AriousError`."""

from __future__ import annotations

from typing import Any


class AriousError(Exception):
    """Base class for every error raised by this SDK."""


class ConfigError(AriousError):
    """The client is misconfigured (no token, no model_name, bad file...)."""


class AuthError(AriousError):
    """HTTP 401/403: the token is missing, wrong, revoked or lacks scope."""

    def __init__(self, message: str, status: int = 401) -> None:
        super().__init__(message)
        self.status = status


class RateLimitError(AriousError):
    """HTTP 429 that survived all retries. ``retry_after`` is in seconds, if sent."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ServerError(AriousError):
    """HTTP 5xx (or another unexpected HTTP status) that survived all retries."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


class TransportError(AriousError):
    """Network failure or timeout that survived all retries."""


class ProtocolError(AriousError):
    """A JSON-RPC error object or an unparseable reply."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class ToolError(AriousError):
    """The tool ran and refused: the MCP result carried ``isError: true``.

    ``str(error)`` is the server's message. ``result`` is the full ToolResult.
    """

    def __init__(self, message: str, result: Any = None) -> None:
        super().__init__(message)
        self.result = result
