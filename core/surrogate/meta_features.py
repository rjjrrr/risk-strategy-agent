from __future__ import annotations

from typing import Any


META_FEATURES = [
    "model_type", "action_type", "feature_type", "semantic_domain", "feature_count_before",
    "feature_count_added", "validation_decision", "iv", "psi", "valid_rate", "novelty",
    "max_correlation", "lr_eligible", "lgbm_eligible", "hypothesis_confidence",
    "feature_credit_before", "hypothesis_credit_before", "baseline_auc", "baseline_ks",
    "baseline_lift10", "baseline_auc_gap", "diagnosis_type", "historical_domain_success_rate",
    "historical_feature_type_success_rate",
]

FORBIDDEN_FUTURE_FIELDS = {
    "result_metrics", "delta_metrics", "counterfactual_decision", "action_outcome", "success",
    "feature_credit", "hypothesis_credit", "metrics_after", "decision",
}


def _num(value: Any, default: float = 0.0) -> float:
    try: return float(value) if value is not None else default
    except (TypeError, ValueError): return default


def build_meta_features(row: dict[str, Any], *, aggregate_lookup: dict | None = None) -> dict[str, Any]:
    """Only execution-time-known fields are accepted; outcome fields never enter X."""
    aggregate_lookup = aggregate_lookup or {}
    validation = row.get("validation_metrics") or {}
    baseline = row.get("baseline_metrics") or {}
    feature_type = str((row.get("feature_types") or [row.get("feature_type") or "UNKNOWN"])[0])
    domain = str((row.get("semantic_domains") or [row.get("semantic_domain") or "UNKNOWN"])[0])
    before_feature_credit = row.get("feature_credit_before") or {}
    before_hypothesis_credit = row.get("hypothesis_credit_before") or {}
    result = {
        "model_type": str(row.get("model_type") or "UNKNOWN"), "action_type": str(row.get("action_type") or "UNKNOWN"),
        "feature_type": feature_type, "semantic_domain": domain,
        "feature_count_before": _num(row.get("feature_count_before")), "feature_count_added": _num(row.get("feature_count_added"), len(row.get("feature_ids") or [])),
        "validation_decision": str(row.get("validation_decision") or validation.get("decision") or "UNKNOWN"),
        "iv": _num(validation.get("iv")), "psi": _num(validation.get("psi")), "valid_rate": _num(validation.get("valid_rate")),
        "novelty": str(row.get("novelty") or validation.get("feature_novelty") or "UNKNOWN"),
        "max_correlation": _num(validation.get("max_existing_correlation") or validation.get("max_correlation")),
        "lr_eligible": int(bool(row.get("lr_eligible", validation.get("lr_eligible", False)))),
        "lgbm_eligible": int(bool(row.get("lgbm_eligible", validation.get("lgbm_eligible", False)))),
        "hypothesis_confidence": str(row.get("hypothesis_confidence") or "UNKNOWN"),
        "feature_credit_before": _num(before_feature_credit.get("smoothed_positive_rate") if isinstance(before_feature_credit, dict) else before_feature_credit),
        "hypothesis_credit_before": _num(before_hypothesis_credit.get("smoothed_positive_rate") if isinstance(before_hypothesis_credit, dict) else before_hypothesis_credit),
        "baseline_auc": _num(baseline.get("oot_auc") or baseline.get("auc")), "baseline_ks": _num(baseline.get("oot_ks") or baseline.get("ks")),
        "baseline_lift10": _num(baseline.get("lift_10") or baseline.get("lift10")),
        "baseline_auc_gap": _num(baseline.get("train_oot_auc_gap") or baseline.get("auc_gap")),
        "diagnosis_type": str(row.get("diagnosis_before") or row.get("diagnosis_type") or "UNKNOWN"),
        "historical_domain_success_rate": _num(aggregate_lookup.get(("SEMANTIC_DOMAIN", domain), {}).get("smoothed_positive_rate"), 0.5),
        "historical_feature_type_success_rate": _num(aggregate_lookup.get(("FEATURE_TYPE", feature_type, str(row.get("model_type") or "UNKNOWN")), {}).get("smoothed_positive_rate"), 0.5),
    }
    assert not (set(result) & FORBIDDEN_FUTURE_FIELDS)
    return result


def targets(row: dict[str, Any]) -> dict[str, float | int]:
    delta = row.get("delta_metrics") or {}
    return {
        "delta_oot_auc": _num(delta.get("delta_oot_auc")),
        "delta_oot_ks": _num(delta.get("delta_oot_ks")),
        "delta_lift10": _num(delta.get("delta_lift10") if delta.get("delta_lift10") is not None else delta.get("delta_lift_10")),
        "positive": int(row.get("counterfactual_decision") == "POSITIVE"),
    }
