from __future__ import annotations

from collections import defaultdict
from .schemas import ContextItem
from .serialization import estimate_tokens, stable_json


def apply_budget(items: list[ContextItem], max_tokens: int, max_per_source: int) -> tuple[list[ContextItem], int, int]:
    selected: list[ContextItem] = []
    counts: dict[str, int] = defaultdict(int)
    used = estimate_tokens('{"context_version":"2"}')
    for item in items:
        if counts[item.source_type] >= max_per_source:
            continue
        cost = estimate_tokens(stable_json(item.model_dump())) + 4
        if used + cost > max_tokens:
            continue
        selected.append(item); counts[item.source_type] += 1; used += cost
    return selected, len(items) - len(selected), used
