from __future__ import annotations

import uuid
from typing import Any

from .config import MAX_HYPOTHESES_PER_ROUND
from .registry import HypothesisRegistry


def _id() -> str:
    return f"H_{uuid.uuid4().hex[:10]}"


class HypothesisAgent:
    def __init__(self, registry: HypothesisRegistry):
        self.registry = registry

    def propose(self, semantics: list[dict[str, Any]], rules: list[dict[str, Any]], limit: int = MAX_HYPOTHESES_PER_ROUND) -> list[dict[str, Any]]:
        proposed = []
        by_name = {row["field"]: row for row in semantics}
        for field, semantic in by_name.items():
            if semantic["confidence"] == "LOW":
                continue
            name = field.lower()
            if "_7d" in name:
                long_field = field.replace("_7d", "_90d")
                if long_field in by_name and by_name[long_field]["confidence"] != "LOW":
                    proposed.append(self._record(
                        "TIME_WINDOW_PATTERN", [field, long_field],
                        f"Recent {field} intensity may accelerate relative to {long_field}",
                        [{"feature_type": "SHORT_LONG_RATIO", "source_fields": [field, long_field]}],
                        "HIGHER_RISK_WHEN_HIGH", "HIGH", "LOW",
                        evidence={"short_window": field, "long_window": long_field},
                    ))
        for rule in rules:
            field = rule.get("field")
            semantic = by_name.get(field)
            if not semantic or semantic["confidence"] == "LOW" or rule.get("grade") not in {"A", "B"}:
                continue
            proposed.append(self._record(
                "UNIVARIATE_SIGNAL", [field], f"Stable rule signal on {field}",
                [{"feature_type": "RAW", "source_fields": [field]}],
                "AS_RULE", "HIGH" if rule.get("oot_status") == "STRONG" else "MEDIUM", "LOW",
                evidence={"rule_id": rule.get("rule_id"), "lift": rule.get("lift"), "oot_status": rule.get("oot_status")},
            ))
        unique = []
        signatures = set()
        for row in proposed:
            signature = (row["evidence_type"], tuple(row["source_fields"]), str(row["candidate_features"]))
            if signature in signatures:
                continue
            signatures.add(signature); self.registry.add(row); unique.append(row)
            if len(unique) >= limit:
                break
        return unique

    def _record(self, evidence_type, source_fields, mechanism, candidates, direction, confidence, cost, evidence):
        return {
            "hypothesis_id": _id(), "evidence_type": evidence_type, "evidence": evidence,
            "risk_mechanism": mechanism, "source_fields": source_fields,
            "candidate_features": candidates, "expected_direction": direction,
            "expected_benefit": "potential incremental OOT discrimination",
            "confidence": confidence, "estimated_cost": cost, "status": "PROPOSED",
            "related_experiments": [],
        }
