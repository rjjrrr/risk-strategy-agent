from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import roc_auc_score, roc_curve

from .config import HARD_GATES, MATERIAL_IMPROVEMENT


def ks_score(y_true, scores) -> float:
    fpr, tpr, _ = roc_curve(y_true, scores)
    return float(np.max(tpr - fpr))


def lift_at(y_true, scores, fraction: float) -> float:
    y = np.asarray(y_true, dtype=float); score = np.asarray(scores, dtype=float)
    n = max(1, int(len(y) * fraction)); selected = y[np.argsort(score)[::-1][:n]]
    base = y.mean()
    return float(selected.mean() / base) if base else 0.0


def score_psi(dev_scores, oot_scores, bins: int = 10) -> float:
    dev = np.asarray(dev_scores); oot = np.asarray(oot_scores)
    edges = np.unique(np.quantile(dev, np.linspace(0, 1, bins + 1)))
    if len(edges) < 2:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    dev_bin = np.digitize(dev, edges[1:-1]); oot_bin = np.digitize(oot, edges[1:-1])
    value = 0.0
    for index in range(len(edges) - 1):
        p = max(float((dev_bin == index).mean()), 1e-6); q = max(float((oot_bin == index).mean()), 1e-6)
        value += (p-q) * np.log(p/q)
    return float(value)


def model_metrics(y_dev, p_dev, y_oot, p_oot, feature_count: int) -> dict[str, Any]:
    dev_auc = float(roc_auc_score(y_dev, p_dev)); oot_auc = float(roc_auc_score(y_oot, p_oot))
    return {
        "dev_auc": dev_auc, "oot_auc": oot_auc,
        "dev_ks": ks_score(y_dev, p_dev), "oot_ks": ks_score(y_oot, p_oot),
        "lift_at_5": lift_at(y_oot, p_oot, .05), "lift_at_10": lift_at(y_oot, p_oot, .10),
        "lift_at_20": lift_at(y_oot, p_oot, .20), "train_oot_auc_gap": abs(dev_auc - oot_auc),
        "score_psi": score_psi(p_dev, p_oot), "feature_count": int(feature_count),
    }


class Evaluator:
    def __init__(self, hard_gates: dict[str, float] | None = None):
        self.gates = {**HARD_GATES, **(hard_gates or {})}

    def hard_gate(self, metrics: dict[str, Any], confirmed_leakage: bool = False, core_feature_psi: float = 0.0) -> tuple[bool, list[str]]:
        failures = []
        if metrics.get("oot_auc", 0) < self.gates["min_oot_auc"]: failures.append("OOT_AUC_BELOW_GATE")
        if metrics.get("oot_ks", 0) < self.gates["min_oot_ks"]: failures.append("OOT_KS_BELOW_GATE")
        if metrics.get("train_oot_auc_gap", 1) > self.gates["max_auc_gap"]: failures.append("AUC_GAP_ABOVE_GATE")
        if core_feature_psi >= self.gates["max_core_feature_psi"]: failures.append("CORE_FEATURE_PSI_ABOVE_GATE")
        if confirmed_leakage: failures.append("CONFIRMED_LEAKAGE")
        return not failures, failures

    def decide(self, before: dict[str, Any] | None, after: dict[str, Any], *, confirmed_leakage: bool = False, core_feature_psi: float = 0.0) -> dict[str, Any]:
        passed, failures = self.hard_gate(after, confirmed_leakage, core_feature_psi)
        if not passed:
            return {"decision": "REJECT", "reason": failures, "hard_gate_passed": False}
        if before is None:
            return {"decision": "ACCEPT_PERFORMANCE", "reason": ["BASELINE_PASSED_HARD_GATE"], "hard_gate_passed": True}
        improvements = {
            "oot_auc": after["oot_auc"] - before["oot_auc"],
            "oot_ks": after["oot_ks"] - before["oot_ks"],
            "lift_at_10": after["lift_at_10"] - before["lift_at_10"],
        }
        no_material_regression = all(improvements[key] >= -threshold for key, threshold in MATERIAL_IMPROVEMENT.items())
        materially_better = any(improvements[key] >= threshold for key, threshold in MATERIAL_IMPROVEMENT.items())
        simpler = after["feature_count"] < before["feature_count"] and all(improvements[key] >= -MATERIAL_IMPROVEMENT[key] for key in improvements)
        if simpler:
            return {"decision": "ACCEPT_SIMPLIFICATION", "reason": improvements, "hard_gate_passed": True}
        if materially_better and no_material_regression:
            return {"decision": "ACCEPT_PERFORMANCE", "reason": improvements, "hard_gate_passed": True}
        return {"decision": "REJECT", "reason": {"NO_MATERIAL_IMPROVEMENT": improvements}, "hard_gate_passed": True}
