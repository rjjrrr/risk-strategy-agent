from __future__ import annotations

import hashlib
import json
from typing import Any

from core.json_utils import sanitize_json


def _latest(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    return list(rows or [])[-count:]


def _best_experiments(rows: list[dict[str, Any]], count: int = 3) -> list[dict[str, Any]]:
    finished = [row for row in rows or [] if row.get("decision") not in {"RUNNING", "FAILED", None}]
    return sorted(finished, key=lambda row: float(row.get("delta_metrics", {}).get("delta_oot_auc") or -999), reverse=True)[:count]


def build_decision_context(raw: dict[str, Any]) -> dict[str, Any]:
    """Build a bounded, deterministic context; never forward full registries to a planner."""
    experiments = list(raw.get("experiment_history") or [])
    rejected: dict[str, int] = {}
    for row in experiments:
        decision = str(row.get("decision") or "UNKNOWN")
        if decision in {"NEGATIVE", "NEUTRAL", "UNSTABLE", "REJECT", "FAILED"}:
            rejected[decision] = rejected.get(decision, 0) + 1
    context = {
        "model_state": raw.get("model_state") or {},
        "current_state": raw.get("current_state") or {},
        "best_state": raw.get("best_state") or {},
        "last_stable_state": raw.get("last_stable_state") or {},
        "feature_validation": _latest(raw.get("feature_validations") or [], 12),
        "feature_credit": _latest(raw.get("feature_credits") or [], 12),
        "hypothesis_credit": _latest(raw.get("hypothesis_credits") or [], 10),
        "counterfactual_history": _latest(raw.get("counterfactual_history") or [], 6),
        "experiment_history": {
            "latest": _latest(experiments, 6),
            "best": _best_experiments(experiments),
            "rejected_summary": rejected,
            "total": len(experiments),
        },
        "data_health": raw.get("data_health") or {},
        "governance": _latest(raw.get("governance") or [], 20),
        "rule_summary": _latest(raw.get("rule_summary") or [], 10),
        "conversation_memory": _latest(raw.get("conversation_memory") or [], 6),
        "candidate_features": _latest(raw.get("candidate_features") or [], 20),
        "hypotheses": _latest(raw.get("hypotheses") or [], 15),
        "confirmed_leakage": list(raw.get("confirmed_leakage") or []),
        "warnings": _latest(raw.get("warnings") or [], 20),
        "segment_mixture": bool(raw.get("segment_mixture", False)),
        "experiment_memory": raw.get("experiment_memory") or {"source": "EXPERIMENT_MEMORY", "summary": {"total": 0}, "similar": [], "historical_winners": [], "relevant_failures": [], "aggregate_credit": {}},
    }
    clean = sanitize_json(context)
    encoded = json.dumps(clean, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return {"context": clean, "context_hash": hashlib.sha256(encoded.encode("utf-8")).hexdigest()}
