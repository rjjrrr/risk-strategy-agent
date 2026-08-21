from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field

FeatureType = Literal["COLUMN_TRANSFORM","RATIO","DIFFERENCE","MISSING_FLAG","TIME_WINDOW_AGG","ENTITY_AGG","CONDITIONAL_AGG","RULE_GROUP_DERIVED","COMPOSITE","UNKNOWN"]
CompilerStatus = Literal["SUPPORTED_TEMPLATE","COMPOSABLE_DSL","NEEDS_NEW_OPERATOR","INSUFFICIENT_DATA","INVALID_SOURCE_FIELD","LEAKAGE_RISK","DATETIME_RAW_FORBIDDEN","UNSUPPORTED_ENTITY","UNSUPPORTED_WINDOW","INVALID_EXPRESSION","REVIEW_REQUIRED","DUPLICATE_FEATURE"]
ExecutionStatus = Literal["NOT_STARTED","RUNNING","SUCCESS","FAILED","BLOCKED"]
DataSource = Literal["CURRENT_WIDE_TABLE","APPLICATION_EVENT_TABLE","DEVICE_RELATION_TABLE","IP_RELATION_TABLE","RULE_GROUP_ARTIFACT"]


def utc_now() -> str: return datetime.now(timezone.utc).isoformat()


class FeatureSpec(BaseModel):
    feature_spec_id: str
    feature_name: str
    business_intent: str
    feature_type: FeatureType = "UNKNOWN"
    source_fields: list[str] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)
    entity_key: str | None = None
    application_time_field: str | None = None
    time_window: str | None = None
    desired_logic: str
    dsl_expression: str | None = None
    desired_operations: list[str] = Field(default_factory=list)
    required_data_sources: list[DataSource] = Field(default_factory=lambda: ["CURRENT_WIDE_TABLE"])
    expected_direction: str | None = None
    hypothesis_id: str | None = None
    proposal_id: str | None = None
    semantic_domain: str = "UNKNOWN"
    input_missing_policy: str = "PRESERVE"
    output_missing_policy: str = "PRESERVE"
    dataset_id: str | None = None
    dataset_version: str | None = None
    created_at: str = Field(default_factory=utc_now)
    version: str = "1.0"


class FeatureCapabilityGap(BaseModel):
    gap_id: str
    feature_spec_id: str
    missing_operator: list[str] = Field(default_factory=list)
    missing_data_source: list[str] = Field(default_factory=list)
    missing_entity_support: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    reason: str
    suggested_resolution: str
    created_at: str = Field(default_factory=utc_now)


class FeatureExecutionPlan(BaseModel):
    plan_id: str
    feature_spec_id: str
    compiler_status: CompilerStatus
    operators: list[str] = Field(default_factory=list)
    source_fields: list[str] = Field(default_factory=list)
    source_features: list[str] = Field(default_factory=list)
    required_sources: list[str] = Field(default_factory=list)
    execution_steps: list[dict[str, Any]] = Field(default_factory=list)
    ast: dict[str, Any] | None = None
    normalized_ast: str | None = None
    dsl_expression: str | None = None
    machine_formula: str | None = None
    human_formula: str | None = None
    estimated_cost: Literal["LOW","MEDIUM","HIGH"] = "LOW"
    leakage_checks: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    capability_gap: FeatureCapabilityGap | None = None
    existing_feature_id: str | None = None
    dataset_version: str | None = None
    created_at: str = Field(default_factory=utc_now)

    @property
    def executable(self) -> bool:
        return self.compiler_status in {"SUPPORTED_TEMPLATE", "COMPOSABLE_DSL"}


class FeatureExecutionResult(BaseModel):
    execution_id: str
    feature_id: str | None = None
    dataset_id: str
    plan_id: str
    status: ExecutionStatus
    started_at: str
    finished_at: str | None = None
    rows: int = 0
    valid_count: int = 0
    missing_count: int = 0
    missing_rate: float | None = None
    statistics: dict[str, Any] = Field(default_factory=dict)
    success: bool = False
    error_type: str | None = None
    error_summary: str | None = None
    artifact_path: str | None = None
    validation_status: str = "NOT_RUN"
    cheap_validation_id: str | None = None
    dataset_version: str | None = None
    created_at: str = Field(default_factory=utc_now)
