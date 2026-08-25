from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


DiagnosisType = Literal[
    "DATA_QUALITY", "LEAKAGE", "LOW_SIGNAL", "OVERFITTING", "FEATURE_DRIFT",
    "REDUNDANCY", "SEGMENT_MIXTURE", "MODEL_MISMATCH", "UNSTABLE_GAIN",
    "INSUFFICIENT_SAMPLE", "NO_ACTION_REQUIRED",
]
ActionType = Literal[
    "TEST_FEATURE", "TEST_HYPOTHESIS", "REMOVE_FEATURE_ABLATION", "MODEL_SWITCH",
    "MODEL_TUNE", "DATA_CLEAN_PROPOSAL", "FEATURE_TRANSFORM_PROPOSAL",
    "REQUEST_ANALYSIS", "REQUEST_MORE_DATA", "ROLLBACK", "STOP_EXPLORATION", "NO_ACTION",
]
LoopStatus = Literal[
    "NOT_STARTED", "RUNNING", "WAITING_APPROVAL", "SUCCESS", "STOPPED", "FAILED",
    "ROLLBACK", "BUDGET_EXHAUSTED",
]
ActionOutcome = Literal[
    "ACCEPT_PERFORMANCE", "ACCEPT_SIMPLIFICATION", "REJECT", "ROLLBACK", "REVIEW", "INCONCLUSIVE",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DecisionEvidence(BaseModel):
    source_id: str
    reason_code: str
    facts: dict[str, Any] = Field(default_factory=dict)


class CandidateAction(BaseModel):
    candidate_id: str | None = None
    action_type: ActionType
    reason: str
    feature_ids: list[str] = Field(default_factory=list)
    hypothesis_id: str | None = None
    feature_type: str = "UNKNOWN"
    semantic_domain: str = "UNKNOWN"
    model_type: Literal["LR", "LGBM"] | None = None
    risk: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    cost: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    evidence_confidence: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"
    novelty: Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"] = "UNKNOWN"
    credit_direction: Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "UNSTABLE", "UNKNOWN"] = "UNKNOWN"
    priority: float = 0.0
    requires_human_approval: bool = False
    historical_credit: dict[str, Any] = Field(default_factory=dict)
    similar_experiments: list[dict[str, Any]] = Field(default_factory=list)
    surrogate_prediction: dict[str, Any] = Field(default_factory=dict)
    expected_delta_auc: float | None = None
    expected_delta_ks: float | None = None
    expected_delta_lift10: float | None = None
    positive_probability: float | None = None
    uncertainty: Literal["LOW", "MEDIUM", "HIGH"] = "HIGH"
    ranking_mode: str = "PHASE5_FALLBACK"
    expected_utility: float = 0.0


class DecisionOutput(BaseModel):
    diagnosis: DiagnosisType
    diagnosis_confidence: Literal["HIGH", "MEDIUM", "LOW"]
    evidence: list[DecisionEvidence] = Field(default_factory=list)
    candidate_actions: list[CandidateAction] = Field(default_factory=list)
    selected_action: CandidateAction | None = None
    expected_effect: str
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    requires_human_approval: bool
    stop_reason: str | None = None
    missing_information: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def selected_action_must_be_candidate(self):
        if self.selected_action and self.selected_action.action_type not in {row.action_type for row in self.candidate_actions}:
            raise ValueError("selected_action must be present in candidate_actions")
        return self


class ExperimentPlan(BaseModel):
    plan_id: str
    decision_id: str
    action_type: ActionType
    hypothesis_id: str | None = None
    feature_ids: list[str] = Field(default_factory=list)
    model_type: Literal["LR", "LGBM"] | None = None
    baseline_state_id: str | None = None
    expected_change: str
    expected_metric_direction: dict[str, Literal["UP", "DOWN", "STABLE", "UNKNOWN"]] = Field(default_factory=dict)
    required_tools: list[str] = Field(default_factory=list)
    risk: Literal["LOW", "MEDIUM", "HIGH"]
    cost: Literal["LOW", "MEDIUM", "HIGH"]
    human_approval_required: bool
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def enforce_single_major_factor(self):
        if self.action_type in {"TEST_FEATURE", "REMOVE_FEATURE_ABLATION"} and len(self.feature_ids) != 1:
            raise ValueError("Feature experiments require exactly one changed feature")
        if self.action_type == "MODEL_SWITCH" and self.feature_ids:
            raise ValueError("MODEL_SWITCH cannot change features in the same experiment")
        return self


class DecisionBudget(BaseModel):
    max_rounds: int = Field(default=3, ge=1, le=10)
    max_experiments_per_round: int = Field(default=3, ge=1, le=10)
    max_total_experiments: int = Field(default=6, ge=1, le=30)
    experiments_used: int = Field(default=0, ge=0)
    experiments_this_round: int = Field(default=0, ge=0)

    @property
    def remaining(self) -> int:
        return max(0, self.max_total_experiments - self.experiments_used)


class DecisionLoopState(BaseModel):
    loop_id: str
    dataset_id: str
    round: int = 0
    current_state_id: str | None = None
    best_state_id: str | None = None
    last_stable_state_id: str | None = None
    active_hypotheses: list[str] = Field(default_factory=list)
    tested_actions: list[dict[str, Any]] = Field(default_factory=list)
    rejected_actions: list[dict[str, Any]] = Field(default_factory=list)
    budget: DecisionBudget = Field(default_factory=DecisionBudget)
    budget_remaining: int = 6
    diagnosis_history: list[dict[str, Any]] = Field(default_factory=list)
    status: LoopStatus = "NOT_STARTED"
    latest_decision_id: str | None = None
    latest_plan_id: str | None = None
    latest_experiment_id: str | None = None
    pending_approval_id: str | None = None
    consecutive_no_gain: int = 0
    blocked_feature_ids: list[str] = Field(default_factory=list)
    stop_reason: str | None = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class ToolCall(BaseModel):
    tool_name: Literal[
        "run_feature_validation", "run_lr_counterfactual", "run_lgbm_counterfactual",
        "run_feature_ablation", "evaluate_model", "get_model_state", "rollback_state",
        "get_feature_credit", "get_hypothesis_credit", "request_analysis_agent",
    ]
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolExecution(BaseModel):
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    status: Literal["SUCCESS", "FAILED", "BLOCKED"]
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    started_at: str
    finished_at: str


class DecisionRecord(BaseModel):
    decision_id: str
    loop_id: str
    diagnosis: DiagnosisType
    evidence: list[DecisionEvidence]
    candidate_actions: list[CandidateAction]
    selected_action: CandidateAction | None
    result: dict[str, Any] = Field(default_factory=dict)
    reason: str
    context_hash: str
    model_state_before: str | None = None
    model_state_after: str | None = None
    experiment_id: str | None = None
    approved_by: str | None = None
    created_at: str = Field(default_factory=utc_now)
