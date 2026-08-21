from __future__ import annotations

from .schemas import ContextItem
from .serialization import content_hash


def deduplicate(items: list[ContextItem]) -> tuple[list[ContextItem], int]:
    seen_ids: set[tuple[str, str]] = set()
    seen_content: set[str] = set()
    output: list[ContextItem] = []
    for item in items:
        identity = (item.source_type, item.source_id)
        digest = content_hash({"title": item.title, "content": item.content})
        if identity in seen_ids or digest in seen_content:
            continue
        seen_ids.add(identity); seen_content.add(digest); output.append(item)
    return output, len(items) - len(output)
