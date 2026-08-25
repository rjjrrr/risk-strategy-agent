from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

NodeStatus = Literal["NOT_STARTED", "RUNNING", "SUCCESS", "FAILED", "WAITING", "SKIPPED", "STALE"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NodeResult(BaseModel):
    node_name: str
    status: NodeStatus
    started_at: str
    finished_at: str | None = None
    input_refs: dict[str, Any] = Field(default_factory=dict)
    output_refs: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    error: dict[str, Any] | None = None


class RiskGraphState(TypedDict, total=False):
    run_id: str
    thread_id: str
    workflow_version: str
    dataset_id: str
    segment: str
    entry_point: str
    conversation_id: str | None
    context_id: str | None
    context_hash: str | None
    hypothesis_ids: list[str]
    proposal_ids: list[str]
    feature_spec_ids: list[str]
    feature_ids: list[str]
    validation_ids: list[str]
    decision_loop_id: str | None
    decision_id: str | None
    plan_id: str | None
    experiment_id: str | None
    current_business_state_id: str | None
    best_business_state_id: str | None
    last_stable_state_id: str | None
    shadow_prediction_ids: list[str]
    approval_status: str
    review_type: str | None
    node_status: dict[str, str]
    errors: list[dict[str, Any]]
    warnings: list[str]
    next_route: str | None
    current_node: str | None
    decision_action: str | None
    validation_decision: str | None
    experiment_outcome: str | None
    decision_round: int
    budget_remaining: int
    requires_approval: bool
    cancel_requested: bool
    continue_workflow: bool
    retry_counts: dict[str, int]
    summaries: dict[str, Any]
    last_node_result: dict[str, Any] | None


def initial_state(**values: Any) -> RiskGraphState:
    return RiskGraphState(
        run_id=values["run_id"], thread_id=values["thread_id"], workflow_version=values.get("workflow_version", "risk-research-v1"),
        dataset_id=values["dataset_id"], segment=values.get("segment", "NEW"), entry_point=values.get("entry_point", "RUN_ALL"),
        conversation_id=values.get("conversation_id"), context_id=None, context_hash=None,
        hypothesis_ids=[values["selected_hypothesis_id"]] if values.get("selected_hypothesis_id") else [], proposal_ids=[values["selected_proposal_id"]] if values.get("selected_proposal_id") else [], feature_spec_ids=[],
        feature_ids=[values["selected_feature_id"]] if values.get("selected_feature_id") else [], validation_ids=[], decision_loop_id=None,
        decision_id=None, plan_id=None, experiment_id=None, current_business_state_id=None, best_business_state_id=None,
        last_stable_state_id=None, shadow_prediction_ids=[], approval_status="NOT_REQUIRED", review_type=None, node_status={},
        errors=[], warnings=[], next_route=None, current_node=None, decision_action=None, validation_decision=None,
        experiment_outcome=None, decision_round=0, budget_remaining=int(values.get("max_total_experiments", 6)), requires_approval=False,
        cancel_requested=False, continue_workflow=True, retry_counts={}, summaries={"selected_proposal_id": values.get("selected_proposal_id")}, last_node_result=None,
    )


FORBIDDEN_STATE_TYPES = ("DataFrame", "Series", "ndarray", "Booster", "LGBMClassifier", "LogisticRegression")


def assert_lightweight(value: Any, path: str = "state") -> None:
    if type(value).__name__ in FORBIDDEN_STATE_TYPES:
        raise TypeError(f"GRAPH_STATE_FORBIDDEN_OBJECT:{path}:{type(value).__name__}")
    if isinstance(value, dict):
        for key, item in value.items(): assert_lightweight(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value): assert_lightweight(item, f"{path}[{index}]")
