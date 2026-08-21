from __future__ import annotations

from typing import Any

MATERIAL = {"delta_oot_auc": 0.005, "delta_oot_ks": 0.01, "delta_lift_10": 0.05}


def delta_metrics(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "delta_oot_auc": "oot_auc", "delta_oot_ks": "oot_ks", "delta_lift_5": "lift_at_5",
        "delta_lift_10": "lift_at_10", "delta_lift_20": "lift_at_20", "delta_auc_gap": "train_oot_auc_gap",
        "delta_score_psi": "score_psi", "delta_feature_count": "feature_count",
    }
    return {name: float(after.get(metric, 0) - before.get(metric, 0)) for name, metric in mapping.items()}


def decide_counterfactual(before: dict[str, Any], after: dict[str, Any], delta: dict[str, Any]) -> str:
    dev_gain = after.get("dev_auc", 0) - before.get("dev_auc", 0)
    unstable = (
        (dev_gain >= 0.005 and delta["delta_oot_auc"] < 0)
        or delta["delta_auc_gap"] > 0.03
        or delta["delta_score_psi"] > 0.1
    )
    if unstable:
        return "UNSTABLE"
    material = any(delta[name] >= threshold for name, threshold in MATERIAL.items())
    no_regression = all(delta[name] >= -threshold for name, threshold in MATERIAL.items())
    if material and no_regression and delta["delta_auc_gap"] <= 0.03 and delta["delta_score_psi"] <= 0.1:
        return "POSITIVE"
    if any(delta[name] <= -threshold for name, threshold in MATERIAL.items()):
        return "NEGATIVE"
    if all(abs(delta[name]) < threshold for name, threshold in MATERIAL.items()):
        return "NEUTRAL"
    return "REVIEW"


def experiment_confidence(oot_rows: int, decision: str, delta: dict[str, Any]) -> str:
    consistent = sum((delta["delta_oot_auc"] > 0, delta["delta_oot_ks"] > 0, delta["delta_lift_10"] > 0)) in {0, 3}
    if oot_rows >= 5000 and consistent and decision not in {"REVIEW", "UNSTABLE"}:
        return "HIGH"
    if oot_rows >= 500:
        return "MEDIUM"
    return "LOW"
