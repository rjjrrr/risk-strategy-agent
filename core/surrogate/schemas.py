from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SurrogateModelRecord(BaseModel):
    surrogate_id: str
    version: str
    algorithm: str
    training_window: dict[str, str | None]
    training_count: int
    features: list[str]
    targets: list[str]
    metrics: dict[str, Any] = Field(default_factory=dict)
    status: Literal["INSUFFICIENT_DATA", "TRAINING", "EXPERIMENTAL", "ACTIVE", "DISABLED_LOW_SIGNAL", "FAILED", "DEPRECATED"]
    artifact: str | None = None
    training_dataset_hash: str
    created_at: str = Field(default_factory=utc_now)


class ExperimentCandidate(BaseModel):
    candidate_id: str
    action_type: str = "TEST_FEATURE"
    feature_id: str | None = None
    hypothesis_id: str | None = None
    model_type: str = "UNKNOWN"
    feature_type: str = "UNKNOWN"
    semantic_domain: str = "UNKNOWN"
    diagnosis_type: str = "UNKNOWN"
    dataset_id: str = "UNKNOWN"
    dataset_version: str = "UNKNOWN"
    validation_metrics: dict[str, Any] = Field(default_factory=dict)
    historical_credit: dict[str, Any] = Field(default_factory=dict)
    surrogate_prediction: dict[str, Any] = Field(default_factory=dict)
    expected_delta_auc: float = 0.0
    expected_delta_ks: float = 0.0
    expected_delta_lift10: float = 0.0
    positive_probability: float = 0.0
    uncertainty: Literal["LOW", "MEDIUM", "HIGH"] = "HIGH"
    novelty: str = "UNKNOWN"
    cost: str = "LOW"
    priority: float = 0.0
    ranking_mode: str = "PHASE5_FALLBACK"
    ranking_reason: str = ""
