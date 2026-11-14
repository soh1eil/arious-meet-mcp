"""Python client for the Arious Meet MCP server (https://api.ariousmeet.com/connect)."""

from ._core import DEFAULT_URL
from ._types import ChatAction, Gif, SearchGifsResult, SendGifResult, ToolResult
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

__version__ = "0.2.0"

__all__ = [
    "DEFAULT_URL",
    "AriousError",
    "AsyncClient",
    "AuthError",
    "ChatAction",
    "Client",
    "ConfigError",
    "Gif",
    "ProtocolError",
    "RateLimitError",
    "SearchGifsResult",
    "SendGifResult",
    "ServerError",
    "ToolError",
    "ToolResult",
    "TransportError",
]
