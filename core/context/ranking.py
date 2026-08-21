from __future__ import annotations

import re
from .schemas import ContextItem, ContextRequest
from .serialization import stable_json

PRIORITY_SCORE = {"CRITICAL": 4.0, "HIGH": 3.0, "MEDIUM": 2.0, "LOW": 1.0}
SOURCE_SCORE = {"DATASET_SUMMARY": 2.0, "DATA_HEALTH": 1.8, "GOVERNANCE": 1.8, "RULE_GROUP": 1.7, "RULE_SUMMARY": 1.5, "MODEL_STATE": 1.4}


def _terms(text: str) -> set[str]:
    return {x.lower() for x in re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", text or "")}


def rank_items(items: list[ContextItem], request: ContextRequest) -> list[ContextItem]:
    query = _terms(request.user_query)
    focus = {x.lower() for x in request.focus_fields}
    for item in items:
        fields = {x.lower() for x in item.field_names}
        body = _terms(item.title + " " + stable_json(item.content))
        item.relevance_score = round(
            PRIORITY_SCORE[item.priority]
            + SOURCE_SCORE.get(item.source_type, 1.0)
            + 4.0 * len(fields & focus)
            + min(3.0, 0.25 * len(body & query)), 4
        )
    return sorted(items, key=lambda x: (-x.relevance_score, x.source_type, x.source_id))
