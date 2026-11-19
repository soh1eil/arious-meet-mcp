"""Python client for the Arious Meet MCP server (https://api.ariousmeet.com/connect)."""

from ._core import DEFAULT_URL
from ._types import (
    ChatAction,
    CheckpointResult,
    ContextAuthor,
    ContextResume,
    ContextVersion,
    Gif,
    PlatformUpdate,
    Prompt,
    PromptArgument,
    PromptMessage,
    PromptResult,
    Redaction,
    SearchGifsResult,
    SendGifResult,
    StartHere,
    ToolResult,
)
from .async_client import AsyncClient
from .client import Client
from .errors import (
    AriousError,
    AuthError,
    ConfigError,
    ContextConflict,
    ProtocolError,
    RateLimitError,
    ServerError,
    ToolError,
    TransportError,
)

__version__ = "0.3.0"

__all__ = [
    "DEFAULT_URL",
    "AriousError",
    "AsyncClient",
    "AuthError",
    "ChatAction",
    "CheckpointResult",
    "Client",
    "ConfigError",
    "ContextAuthor",
    "ContextConflict",
    "ContextResume",
    "ContextVersion",
    "Gif",
    "PlatformUpdate",
    "Prompt",
    "PromptArgument",
    "PromptMessage",
    "PromptResult",
    "ProtocolError",
    "RateLimitError",
    "Redaction",
    "SearchGifsResult",
    "SendGifResult",
    "ServerError",
    "StartHere",
    "ToolError",
    "ToolResult",
    "TransportError",
]
