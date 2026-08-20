from __future__ import annotations

from typing import Any

from .evaluation import Evaluator


class FeatureAblationEvaluator:
    """Evaluate one-at-a-time removals without mutating the active model state."""

    def __init__(self, evaluator: Evaluator | None = None):
        self.evaluator = evaluator or Evaluator()

    def assess(self, full_metrics: dict[str, Any], removal_results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        rows=[]
        for feature, metrics in removal_results.items():
            decision=self.evaluator.decide(full_metrics,metrics)
            removable=decision["decision"]=="ACCEPT_SIMPLIFICATION"
            rows.append({
                "feature":feature, "metrics_without_feature":metrics,
                "decision":"REMOVE_CANDIDATE" if removable else "KEEP",
                "requires_human_approval":removable,
                "evaluator_decision":decision,
            })
        return rows
