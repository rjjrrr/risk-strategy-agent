from __future__ import annotations

from typing import Any


CONFIDENCE_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
COST_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


class PlannerAgent:
    """Selects one next experiment; never trains models."""

    def choose(
        self, hypotheses: list[dict[str, Any]], experiments: list[dict[str, Any]],
        remaining_budget: dict[str, int], diagnosis: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if remaining_budget.get("experiments", 0) <= 0:
            return {"action": "STOP", "reason": "EXPERIMENT_BUDGET_EXHAUSTED"}
        if diagnosis:
            priority = ["DATA_QUALITY", "LEAKAGE", "FEATURE_DRIFT", "OVERFITTING", "LOW_SIGNAL", "MODEL_MISMATCH"]
            top = min(diagnosis, key=lambda row: priority.index(row["diagnosis_type"]) if row["diagnosis_type"] in priority else len(priority))
            if top.get("requires_human"):
                return {"action": "WAITING_APPROVAL", "reason": top["diagnosis_type"], "diagnosis_id": top["diagnosis_id"]}
        rejected_hypotheses = {row.get("hypothesis_id") for row in experiments if row.get("decision") == "REJECT"}
        candidates = [row for row in hypotheses if row.get("status") in {"PROPOSED", "SUPPORTED"} and row.get("hypothesis_id") not in rejected_hypotheses]
        if not candidates:
            return {"action": "STOP", "reason": "NO_UNTESTED_HYPOTHESIS"}
        candidates.sort(key=lambda row: (CONFIDENCE_ORDER.get(row.get("confidence"), 9), COST_ORDER.get(row.get("estimated_cost"), 9), row.get("created_at", "")))
        selected = candidates[0]
        return {
            "action": "RUN_EXPERIMENT", "hypothesis_id": selected["hypothesis_id"],
            "experiment_type": "FEATURE_ADD", "reason": selected["risk_mechanism"],
            "expected_gain": selected.get("expected_benefit"), "confidence": selected.get("confidence"),
            "cost": selected.get("estimated_cost"),
        }

    @staticmethod
    def stop_reason(state: dict[str, Any], experiments: list[dict[str, Any]], high_confidence_remaining: bool = True) -> str | None:
        if state.get("pending_human_approval"):
            return "HUMAN_APPROVAL_PENDING"
        if state.get("round_index", 0) >= state.get("max_rounds", 3):
            return "MAX_AGENT_ROUNDS_REACHED"
        recent = [row for row in experiments if row.get("decision") in {"REJECT", "REVIEW"}][-2:]
        if len(recent) == 2:
            return "TWO_ROUNDS_WITHOUT_MATERIAL_IMPROVEMENT"
        if state.get("budget", {}).get("experiments", 0) <= 0:
            return "EXPERIMENT_BUDGET_EXHAUSTED"
        return None
