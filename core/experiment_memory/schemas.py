from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


Outcome = Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "UNSTABLE", "FAILED", "REVIEW", "RUNNING"]


class ExperimentMemoryRecord(BaseModel):
    experiment_id: str
    timestamp: str = Field(default_factory=utc_now)
    dataset_id: str
    dataset_version: str = "UNKNOWN"
    data_source: str = "CURRENT_WIDE_TABLE"
    segment: str = "NEW"
    model_type: str = "UNKNOWN"
    action_type: str = "TEST_FEATURE"
    hypothesis_id: str | None = None
    feature_ids: list[str] = Field(default_factory=list)
    feature_types: list[str] = Field(default_factory=list)
    semantic_domains: list[str] = Field(default_factory=list)
    evidence_types: list[str] = Field(default_factory=list)
    baseline_state_id: str | None = None
    baseline_metrics: dict[str, Any] = Field(default_factory=dict)
    result_metrics: dict[str, Any] = Field(default_factory=dict)
    delta_metrics: dict[str, Any] = Field(default_factory=dict)
    counterfactual_decision: str = "REVIEW"
    action_outcome: str = "INCONCLUSIVE"
    feature_credit: dict[str, Any] = Field(default_factory=dict)
    hypothesis_credit: dict[str, Any] = Field(default_factory=dict)
    diagnosis_before: str = "UNKNOWN"
    state_after: str | None = None
    cost: float = 0.0
    runtime: float = 0.0
    human_approval: bool = False
    success: bool = False
    validation_metrics: dict[str, Any] = Field(default_factory=dict)
    feature_count_before: int = 0
    source: Literal["REAL", "SYNTHETIC"] = "REAL"
    memory_source: Literal["REAL", "SYNTHETIC"] = "REAL"
    experiment_signature: str


class AggregateCredit(BaseModel):
    dimension: str
    value: str
    model_type: str | None = None
    dataset_id: str | None = None
    experiment_count: int
    sample_count: int
    failed_count: int
    positive_count: int
    neutral_count: int
    negative_count: int
    unstable_count: int
    positive_rate: float
    smoothed_positive_rate: float
    avg_delta_auc: float
    avg_delta_ks: float
    avg_delta_lift10: float
    stability_rate: float
    rollback_rate: float
    average_cost: float
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
