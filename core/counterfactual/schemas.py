from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

CounterfactualDecision = Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "UNSTABLE", "REVIEW", "RUNNING", "FAILED", "DUPLICATE_EXPERIMENT"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CounterfactualExperiment(BaseModel):
    experiment_id: str
    feature_id: str
    feature_version: str
    hypothesis_id: str | None = None
    dataset_id: str
    experiment_type: Literal["FEATURE_ADD", "FEATURE_REMOVE", "FEATURE_GROUP_REMOVE"] = "FEATURE_ADD"
    baseline_state_id: str
    challenger_state_id: str
    model_type: Literal["LR", "LGBM"]
    baseline_features: list[str]
    challenger_features: list[str]
    changed_features: list[str]
    model_params: dict[str, Any]
    model_params_hash: str
    split_id: str
    split_hash: str
    seed: int
    preprocessing_version: str
    feature_pool_version: str
    metrics_before: dict[str, Any]
    metrics_after: dict[str, Any]
    delta_metrics: dict[str, Any]
    consistency_checks: dict[str, bool]
    decision: CounterfactualDecision
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"
    error: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)
    finished_at: str | None = None


class FeatureCredit(BaseModel):
    feature_id: str
    model_type: Literal["LR", "LGBM"]
    performance_credit: Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "UNKNOWN"]
    stability_credit: Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "UNKNOWN"]
    simplicity_credit: Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "UNKNOWN"]
    drift_penalty: Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
    cost_penalty: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    overall_direction: Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "UNSTABLE", "INCONCLUSIVE"]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    experiment_count: int
    simplification_candidate: bool = False
    updated_at: str = Field(default_factory=utc_now)


class FeatureMarginalGain(BaseModel):
    gain_id: str
    feature_id: str
    feature_version: str
    model_type: Literal["LR", "LGBM"]
    experiment_id: str
    delta_oot_auc: float
    delta_oot_ks: float
    delta_lift_5: float
    delta_lift_10: float
    delta_lift_20: float
    delta_auc_gap: float
    delta_score_psi: float
    delta_feature_count: float
    conclusion: Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "UNSTABLE", "REVIEW"]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    created_at: str = Field(default_factory=utc_now)


class HypothesisCredit(BaseModel):
    hypothesis_id: str
    tested_features: list[str]
    positive_features: list[str]
    neutral_features: list[str]
    negative_features: list[str]
    best_delta_auc: float = 0.0
    best_delta_ks: float = 0.0
    best_delta_lift10: float = 0.0
    support_status: Literal["PROPOSED", "TESTING", "SUPPORTED", "PARTIALLY_SUPPORTED", "REJECTED", "INCONCLUSIVE"]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    updated_at: str = Field(default_factory=utc_now)
