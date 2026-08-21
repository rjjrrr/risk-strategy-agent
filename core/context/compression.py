from __future__ import annotations

from typing import Any


def compact(value: Any, *, depth: int = 0) -> Any:
    """Compress content structurally; never cut serialized JSON mid-document."""
    if depth > 5:
        return "[nested content omitted]"
    if isinstance(value, dict):
        return {str(k): compact(v, depth=depth + 1) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [compact(v, depth=depth + 1) for v in value[:30]]
    if isinstance(value, str) and len(value) > 800:
        return value[:797] + "..."
    return value
