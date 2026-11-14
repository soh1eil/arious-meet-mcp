"""Python client for the Arious Meet MCP server (https://api.ariousmeet.com/connect)."""

from ._core import DEFAULT_URL
from ._types import ToolResult
from .async_client import AsyncClient
from .client import Client
from .errors import (
    AriousError,
    AuthError,
    ConfigError,
    ProtocolError,
    RateLimitError,
    ServerError,
    ToolError,
    TransportError,
)

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_URL",
    "AriousError",
    "AsyncClient",
    "AuthError",
    "Client",
    "ConfigError",
    "ProtocolError",
    "RateLimitError",
    "ServerError",
    "ToolError",
    "ToolResult",
    "TransportError",
]
