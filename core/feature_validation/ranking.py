from __future__ import annotations


DECISION_ORDER = {"PROMISING": 0, "EXPLORATORY": 1, "REVIEW": 2, "REJECTED": 3}


def rank_validations(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: (DECISION_ORDER.get(row.get("decision"), 9), -(row.get("metrics", {}).get("lift") or 0)))
