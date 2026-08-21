from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

ValidationDecision = Literal["PROMISING", "EXPLORATORY", "REVIEW", "REJECTED"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FeatureValidationResult(BaseModel):
    validation_id: str
    feature_id: str
    feature_version: str
    dataset_id: str
    segment: str = "NEW"
    metrics: dict[str, Any]
    decision: ValidationDecision
    lr_eligible: bool
    lgbm_eligible: bool
    eligibility_reasons: dict[str, list[str]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)
