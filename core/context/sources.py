from __future__ import annotations

from typing import Any
from .schemas import ContextItem


def item(source_type: str, source_id: str, title: str, content: dict[str, Any], *, priority: str = "MEDIUM", fields: list[str] | None = None, created_at: str | None = None, tags: list[str] | None = None) -> ContextItem:
    return ContextItem(source_type=source_type, source_id=str(source_id), title=title, content=content, priority=priority, field_names=fields or [], created_at=created_at, tags=tags or [])
