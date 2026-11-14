from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChatAction(str, Enum):
    """What the agent is doing, for ``send_chat_action`` / ``send_typing(action=...)``.

    The notice fades after about 5 seconds; repeat it about every 4 seconds while the
    work goes on. ``CANCEL`` clears it at once.
    """

    TYPING = "typing"
    UPLOAD_PHOTO = "upload_photo"
    UPLOAD_VIDEO = "upload_video"
    RECORD_VOICE = "record_voice"
    UPLOAD_VOICE = "upload_voice"
    UPLOAD_DOCUMENT = "upload_document"
    RECORD_VIDEO_NOTE = "record_video_note"
    UPLOAD_VIDEO_NOTE = "upload_video_note"
    CHOOSE_STICKER = "choose_sticker"
    FIND_LOCATION = "find_location"
    CANCEL = "cancel"


@dataclass
class ToolResult:
    """Result of a tools/call."""

    text: str = ""
    structured: dict[str, Any] | None = None
    content: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False

    @property
    def data(self) -> Any:
        """Structured content if present, else the text parsed as JSON, else the text."""
        if self.structured is not None:
            return self.structured
        try:
            return json.loads(self.text)
        except ValueError:
            return self.text

    @classmethod
    def from_wire(cls, raw: dict[str, Any]) -> ToolResult:
        content = [c for c in raw.get("content") or [] if isinstance(c, dict)]
        text = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
        structured = raw.get("structuredContent")
        return cls(
            text=text,
            structured=structured if isinstance(structured, dict) else None,
            content=content,
            is_error=bool(raw.get("isError")),
        )


@dataclass
class Gif:
    """One ``search_gifs`` result. ``preview_url`` is valid for about an hour."""

    gif_id: str
    title: str = ""
    width: int = 0
    height: int = 0
    content_type: str = ""
    source: str = ""
    preview_url: str | None = None

    @classmethod
    def from_wire(cls, raw: dict[str, Any]) -> Gif:
        return cls(
            gif_id=str(raw.get("gif_id", "")),
            title=str(raw.get("title", "")),
            width=int(raw.get("width") or 0),
            height=int(raw.get("height") or 0),
            content_type=str(raw.get("content_type", "")),
            source=str(raw.get("source", "")),
            preview_url=raw.get("preview_url"),
        )


@dataclass
class SearchGifsResult:
    """Typed view of a ``search_gifs`` result; ``busy`` means the live GIF source was busy."""

    gifs: list[Gif] = field(default_factory=list)
    busy: bool = False

    @classmethod
    def from_result(cls, result: ToolResult) -> SearchGifsResult:
        data = result.structured or {}
        return cls(
            gifs=[Gif.from_wire(g) for g in data.get("gifs") or [] if isinstance(g, dict)],
            busy=bool(data.get("busy")),
        )


@dataclass
class SendGifResult:
    """Typed view of a ``send_gif`` result."""

    message_id: str
    conversation_id: str
    attachment_id: str
    gif_id: str
    sent_via_grant_name: str | None = None

    @classmethod
    def from_result(cls, result: ToolResult) -> SendGifResult:
        data = result.structured or {}
        return cls(
            message_id=str(data.get("message_id", "")),
            conversation_id=str(data.get("conversation_id", "")),
            attachment_id=str(data.get("attachment_id", "")),
            gif_id=str(data.get("gif_id", "")),
            sent_via_grant_name=data.get("sent_via_grant_name"),
        )
