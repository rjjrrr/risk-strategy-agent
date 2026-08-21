from __future__ import annotations

from collections import defaultdict

from .schemas import FeatureCredit, HypothesisCredit


def build_feature_credit(feature_id: str, model_type: str, experiments: list[dict], validation: dict | None = None) -> FeatureCredit | None:
    rows = [row for row in experiments if row.get("feature_id") == feature_id and row.get("model_type") == model_type and row.get("decision") not in {"FAILED", "RUNNING"}]
    if not rows:
        return None
    latest = rows[-1]
    decision = latest["decision"]
    performance = "POSITIVE" if decision == "POSITIVE" else "NEGATIVE" if decision == "NEGATIVE" else "NEUTRAL" if decision == "NEUTRAL" else "UNKNOWN"
    stability = "NEGATIVE" if decision == "UNSTABLE" else "POSITIVE" if latest.get("delta_metrics", {}).get("delta_score_psi", 0) < -0.02 else "NEUTRAL"
    remove_neutral = latest.get("experiment_type") == "FEATURE_REMOVE" and decision == "NEUTRAL"
    simplicity = "POSITIVE" if remove_neutral else "NEUTRAL"
    psi = (validation or {}).get("metrics", {}).get("psi")
    drift = "HIGH" if psi is not None and psi >= 0.25 else "MEDIUM" if psi is not None and psi >= 0.1 else "LOW"
    overall = decision if decision in {"POSITIVE", "NEUTRAL", "NEGATIVE", "UNSTABLE"} else "INCONCLUSIVE"
    return FeatureCredit(
        feature_id=feature_id, model_type=model_type, performance_credit=performance,
        stability_credit=stability, simplicity_credit=simplicity, drift_penalty=drift,
        overall_direction=overall, confidence=latest.get("confidence", "LOW"),
        experiment_count=len(rows), simplification_candidate=remove_neutral,
    )


def build_hypothesis_credit(hypothesis_id: str, experiments: list[dict]) -> HypothesisCredit:
    rows = [row for row in experiments if row.get("hypothesis_id") == hypothesis_id and row.get("decision") not in {"FAILED", "RUNNING"}]
    by_feature: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        by_feature[str(row["feature_id"])].append(str(row["decision"]))
    positive = sorted(feature for feature, decisions in by_feature.items() if "POSITIVE" in decisions)
    negative = sorted(feature for feature, decisions in by_feature.items() if decisions and all(x in {"NEGATIVE", "UNSTABLE"} for x in decisions))
    neutral = sorted(set(by_feature) - set(positive) - set(negative))
    if not rows:
        status = "PROPOSED"
    elif positive and not negative:
        status = "SUPPORTED"
    elif positive:
        status = "PARTIALLY_SUPPORTED"
    elif len(negative) >= 3 and not neutral:
        status = "REJECTED"
    elif any(row.get("decision") in {"RUNNING"} for row in experiments if row.get("hypothesis_id") == hypothesis_id):
        status = "TESTING"
    else:
        status = "INCONCLUSIVE"
    deltas = [row.get("delta_metrics", {}) for row in rows]
    confidence = "HIGH" if len(by_feature) >= 3 else "MEDIUM" if rows else "LOW"
    return HypothesisCredit(
        hypothesis_id=hypothesis_id, tested_features=sorted(by_feature), positive_features=positive,
        neutral_features=neutral, negative_features=negative,
        best_delta_auc=max([x.get("delta_oot_auc", 0) for x in deltas] or [0]),
        best_delta_ks=max([x.get("delta_oot_ks", 0) for x in deltas] or [0]),
        best_delta_lift10=max([x.get("delta_lift_10", 0) for x in deltas] or [0]),
        support_status=status, confidence=confidence,
    )
