from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


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
