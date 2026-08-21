from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable

from .budget import apply_budget
from .compression import compact
from .dedup import deduplicate
from .ranking import rank_items
from .schemas import ContextBundle, ContextItem, ContextRequest
from .serialization import content_hash, estimate_tokens, stable_json


class ContextBuilder:
    VERSION = "context-builder-v2"

    def build(self, request: ContextRequest, source_items: Iterable[ContextItem]) -> ContextBundle:
        compressed = [item.model_copy(update={"content": compact(item.content)}) for item in source_items]
        unique, duplicate_count = deduplicate(compressed)
        ranked = rank_items(unique, request)
        selected, dropped, _ = apply_budget(ranked, request.max_context_tokens, request.max_items_per_source)
        payload = {"context_version": self.VERSION, "dataset_id": request.dataset_id, "agent_type": request.agent_type, "items": [x.model_dump() for x in selected]}
        text = stable_json(payload)
        digest = content_hash(payload)
        source_counts: dict[str, int] = {}
        for item in selected:
            source_counts[item.source_type] = source_counts.get(item.source_type, 0) + 1
        return ContextBundle(
            context_id=f"CTX_{uuid.uuid4().hex[:12]}", request=request, items=selected, text=text,
            context_hash=digest, included_items=len(selected), dropped_items=dropped,
            deduplicated_items=duplicate_count, estimated_context_tokens=estimate_tokens(text),
            sources_used=sorted(source_counts), source_counts=source_counts,
            versions={"builder": self.VERSION, "schema": "context-schema-v1"},
            created_at=datetime.now(timezone.utc).isoformat(),
        )
