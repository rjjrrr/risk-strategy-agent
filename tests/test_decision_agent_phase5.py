from __future__ import annotations

import pytest
import pandas as pd
from pydantic import ValidationError
from fastapi.testclient import TestClient

from core.decision_agent.loop import DecisionLoopManager
from core.decision_agent.registry import DecisionToolAuditRegistry
from core.decision_agent.schemas import DecisionBudget, DecisionOutput, ExperimentPlan
from core.decision_agent.tools import ControlledToolRegistry
from core.decision_agent.schemas import ToolCall
from backend.app import config
from backend.app.main import app
from backend.app.services import analysis_service


def base_context(**changes):
    base = {
        "model_state": {"model_type": "LR", "metrics": {"dev_auc": 0.68, "oot_auc": 0.66, "train_oot_auc_gap": 0.02}},
        "current_state": {"state_id": "S_CURRENT", "metrics": {"dev_auc": 0.68, "oot_auc": 0.66, "train_oot_auc_gap": 0.02}},
        "best_state": {"state_id": "S_BEST"}, "last_stable_state": {"state_id": "S_STABLE"},
        "feature_validations": [], "feature_credits": [], "hypothesis_credits": [],
        "counterfactual_history": [], "experiment_history": [], "candidate_features": [],
        "hypotheses": [], "data_health": {"sample_size": 5000, "minimum_sample": 500},
        "governance": [], "rule_summary": [], "conversation_memory": [], "confirmed_leakage": [],
    }
    return {**base, **changes}


def candidate(feature_id, decision="PROMISING", hypothesis_id="H1"):
    return {"feature_id": feature_id, "hypothesis_id": hypothesis_id, "confidence": "HIGH", "estimated_cost": "LOW", "validation_result": {"decision": decision, "lr_eligible": True, "lgbm_eligible": True, "metrics": {"feature_novelty": "HIGH"}}}


def make_manager(tmp_path, context, *, llm=None, outcomes=None):
    state = {"current_state_id": "S_CURRENT", "best_state_id": "S_BEST", "last_stable_state_id": "S_STABLE", "active_hypotheses": ["H1"]}
    outcomes = outcomes or {}
    audit = DecisionToolAuditRegistry(tmp_path / "decision")
    tools = ControlledToolRegistry(audit)

    def experiment(feature_id, model_type, experiment_type="FEATURE_ADD"):
        value = outcomes.get(feature_id, "POSITIVE")
        if value == "FAILED":
            raise RuntimeError("training failed")
        return {"experiment_id": f"E_{feature_id}_{experiment_type}", "decision": value, "delta_metrics": {"delta_oot_auc": 0.01 if value == "POSITIVE" else 0.0}, "feature_credit": None if value == "FAILED" else {"overall_direction": value}, "hypothesis_credit": {"support_status": "SUPPORTED" if value == "POSITIVE" else "INCONCLUSIVE"}}

    tools.register("run_lr_counterfactual", lambda dataset_id, feature_id, experiment_type="FEATURE_ADD", seed=42: experiment(feature_id, "LR", experiment_type))
    tools.register("run_lgbm_counterfactual", lambda dataset_id, feature_id, experiment_type="FEATURE_ADD", seed=42: experiment(feature_id, "LGBM", experiment_type))
    tools.register("run_feature_ablation", lambda dataset_id, feature_id, model_type, seed=42: experiment(feature_id, model_type, "FEATURE_REMOVE"))
    tools.register("rollback_state", lambda dataset_id, state_id=None: state.update(current_state_id=state_id or "S_STABLE") or {"decision": "ROLLBACK", "state_id": state["current_state_id"]})
    tools.register("evaluate_model", lambda dataset_id, state_id=None, model_type=None: {"decision": "POSITIVE", "model_type": model_type})
    tools.register("request_analysis_agent", lambda dataset_id, reason, focus_fields=None: {"decision": "REVIEW", "request_status": "PENDING_ANALYSIS"})
    tools.register("run_feature_validation", lambda dataset_id, feature_id, time_field=None: {"decision": "PROMISING"})
    tools.register("get_model_state", lambda dataset_id: state)
    tools.register("get_feature_credit", lambda dataset_id, feature_id, model_type=None: {"items": []})
    tools.register("get_hypothesis_credit", lambda dataset_id, hypothesis_id: {"support_status": "PROPOSED"})
    manager = DecisionLoopManager(tmp_path / "decision", "D1", tools, context_provider=lambda _: context, state_provider=lambda _: state, llm_decider=llm)
    return manager, state, audit


def test_decision_schema():
    value = DecisionOutput.model_validate({"diagnosis": "NO_ACTION_REQUIRED", "diagnosis_confidence": "HIGH", "evidence": [], "candidate_actions": [{"action_type": "NO_ACTION", "reason": "stable"}], "selected_action": {"action_type": "NO_ACTION", "reason": "stable"}, "expected_effect": "Preserve current state", "risk_level": "LOW", "requires_human_approval": False, "missing_information": []})
    assert value.selected_action.action_type == "NO_ACTION"
    with pytest.raises(ValidationError):
        ExperimentPlan(plan_id="P", decision_id="D", action_type="TEST_FEATURE", feature_ids=["F1", "F2"], expected_change="x", risk="LOW", cost="LOW", human_approval_required=False)


def test_decision_low_signal(tmp_path):
    context = base_context(experiment_history=[{"decision": "NEUTRAL"}, {"decision": "NEUTRAL"}])
    manager, _, _ = make_manager(tmp_path, context)
    loop = manager.create(); state = manager.diagnose(loop["loop_id"]); decision = manager.decisions.get(state["latest_decision_id"])
    assert decision["diagnosis"] == "LOW_SIGNAL" and decision["selected_action"]["action_type"] == "STOP_EXPLORATION"


def test_decision_overfitting(tmp_path):
    context = base_context(current_state={"state_id": "S_CURRENT", "metrics": {"dev_auc": 0.82, "oot_auc": 0.61, "train_oot_auc_gap": 0.21}})
    manager, _, _ = make_manager(tmp_path, context); state = manager.diagnose(manager.create()["loop_id"]); decision = manager.decisions.get(state["latest_decision_id"])
    assert decision["diagnosis"] == "OVERFITTING" and decision["selected_action"]["action_type"] == "ROLLBACK"


def test_decision_drift(tmp_path):
    context = base_context(feature_validations=[{"feature_id": "F_DRIFT", "metrics": {"psi": 0.8}}], candidate_features=[candidate("F_DRIFT")])
    manager, _, _ = make_manager(tmp_path, context); state = manager.diagnose(manager.create()["loop_id"]); decision = manager.decisions.get(state["latest_decision_id"])
    assert decision["diagnosis"] == "FEATURE_DRIFT" and decision["selected_action"]["action_type"] == "REMOVE_FEATURE_ABLATION"


def test_decision_redundancy(tmp_path):
    context = base_context(feature_validations=[{"feature_id": "F_RED", "metrics": {"max_existing_correlation": 0.99, "feature_novelty": "LOW"}}], counterfactual_history=[{"feature_id": "F_RED", "decision": "NEUTRAL"}])
    manager, _, _ = make_manager(tmp_path, context); state = manager.diagnose(manager.create()["loop_id"]); decision = manager.decisions.get(state["latest_decision_id"])
    assert decision["diagnosis"] == "REDUNDANCY" and decision["selected_action"]["feature_ids"] == ["F_RED"]


def test_decision_model_mismatch(tmp_path):
    history = [{"feature_id": "F2", "model_type": "LR", "decision": "NEUTRAL"}, {"feature_id": "F2", "model_type": "LGBM", "decision": "POSITIVE"}]
    manager, _, _ = make_manager(tmp_path, base_context(counterfactual_history=history)); state = manager.diagnose(manager.create()["loop_id"]); decision = manager.decisions.get(state["latest_decision_id"])
    assert decision["diagnosis"] == "MODEL_MISMATCH" and decision["selected_action"]["action_type"] == "MODEL_SWITCH"


def test_decision_leakage(tmp_path):
    manager, _, _ = make_manager(tmp_path, base_context(confirmed_leakage=["F_LEAK"])); state = manager.diagnose(manager.create()["loop_id"]); decision = manager.decisions.get(state["latest_decision_id"])
    assert decision["diagnosis"] == "LEAKAGE" and state["blocked_feature_ids"] == ["F_LEAK"] and decision["selected_action"]["action_type"] == "STOP_EXPLORATION"


def test_decision_training_failure(tmp_path):
    manager, state_store, _ = make_manager(tmp_path, base_context(candidate_features=[candidate("F_FAIL")]), outcomes={"F_FAIL": "FAILED"})
    loop = manager.create(); planned = manager.diagnose(loop["loop_id"]); finished = manager.execute(loop["loop_id"]); record = manager.decisions.get(planned["latest_decision_id"])
    assert finished["status"] == "ROLLBACK" and state_store["current_state_id"] == "S_STABLE"
    assert record["result"]["feature_credit"] is None


def test_decision_budget(tmp_path):
    manager, _, audit = make_manager(tmp_path, base_context(candidate_features=[candidate("F2")]))
    budget = DecisionBudget(max_total_experiments=1, experiments_used=1)
    loop = manager.create(budget); state = manager.diagnose(loop["loop_id"])
    assert state["status"] == "BUDGET_EXHAUSTED" and audit.all() == []


def test_decision_stop(tmp_path):
    context = base_context(candidate_features=[candidate("F1"), candidate("F2")])
    manager, _, _ = make_manager(tmp_path, context, outcomes={"F1": "NEUTRAL", "F2": "NEUTRAL"})
    loop = manager.create(); manager.diagnose(loop["loop_id"]); first = manager.execute(loop["loop_id"]); assert first["status"] == "RUNNING"
    manager.diagnose(loop["loop_id"]); second = manager.execute(loop["loop_id"])
    assert second["status"] == "STOPPED" and second["stop_reason"] == "TWO_EXPERIMENTS_WITHOUT_MATERIAL_GAIN"


def test_decision_approval_gate(tmp_path):
    manager, _, audit = make_manager(tmp_path, base_context(data_health={"sample_size": 5000, "minimum_sample": 500, "severe_issue": True}))
    loop = manager.create(); waiting = manager.diagnose(loop["loop_id"])
    assert waiting["status"] == "WAITING_APPROVAL"
    with pytest.raises(ValueError, match="HUMAN_APPROVAL_REQUIRED"):
        manager.execute(loop["loop_id"])
    approved = manager.approve(loop["loop_id"], "risk-owner")
    assert approved["status"] == "RUNNING" and audit.all() == []


def test_decision_rollback(tmp_path):
    manager, state_store, audit = make_manager(tmp_path, base_context())
    loop = manager.create(); result = manager.rollback(loop["loop_id"])
    assert result["status"] == "ROLLBACK" and state_store["current_state_id"] == "S_STABLE" and audit.all()[0]["tool_name"] == "rollback_state"


def test_decision_feedback_context(tmp_path):
    manager, _, _ = make_manager(tmp_path, base_context(candidate_features=[candidate("F2")]))
    loop = manager.create(); manager.diagnose(loop["loop_id"]); manager.execute(loop["loop_id"]); feedback = manager.feedback_context(loop["loop_id"])
    assert feedback["previous_action"]["action_type"] == "TEST_FEATURE" and feedback["experiment_id"].startswith("E_F2")
    assert feedback["experiment_result"]["feature_credit"] and feedback["state_change"]["current"]


def test_decision_no_metric_hallucination(tmp_path):
    manager, _, _ = make_manager(tmp_path, base_context(candidate_features=[candidate("F2")]))
    state = manager.diagnose(manager.create()["loop_id"]); decision = manager.decisions.get(state["latest_decision_id"])
    assert "0.03" not in decision["expected_effect"]
    assert all(set(item["facts"]) <= {"oot_auc", "dev_auc", "train_oot_auc_gap", "auc_gap"} or item["reason_code"] != "LOW_OOT_SIGNAL" for item in decision["evidence"])


def test_llm_failure_no_mock_execution(tmp_path):
    def failed_llm(_):
        raise RuntimeError("provider unavailable")
    manager, _, audit = make_manager(tmp_path, base_context(candidate_features=[candidate("F2")]), llm=failed_llm)
    state = manager.diagnose(manager.create()["loop_id"], use_llm=True)
    assert state["status"] == "STOPPED" and state["stop_reason"].startswith("LLM_FAILED") and audit.all() == []


def test_case_a_positive_history_selects_promising_f2(tmp_path):
    context = base_context(candidate_features=[candidate("F2")], feature_credits=[{"feature_id": "F1", "overall_direction": "POSITIVE"}], hypothesis_credits=[{"hypothesis_id": "H1", "support_status": "SUPPORTED"}])
    manager, _, _ = make_manager(tmp_path, context); state = manager.diagnose(manager.create()["loop_id"]); decision = manager.decisions.get(state["latest_decision_id"])
    assert decision["selected_action"]["action_type"] == "TEST_FEATURE" and decision["selected_action"]["feature_ids"] == ["F2"]


def test_simplification_requires_permanent_removal_approval(tmp_path):
    context = base_context(feature_validations=[{"feature_id": "F_RED", "metrics": {"max_existing_correlation": 0.99}}], counterfactual_history=[{"feature_id": "F_RED", "decision": "NEUTRAL"}])
    manager, _, _ = make_manager(tmp_path, context, outcomes={"F_RED": "NEUTRAL"})
    loop = manager.create(); manager.diagnose(loop["loop_id"]); state = manager.execute(loop["loop_id"])
    assert state["status"] == "WAITING_APPROVAL" and state["stop_reason"] == "PERMANENT_FEATURE_REMOVE_REQUIRES_APPROVAL"


def test_decision_api_lifecycle(tmp_path, monkeypatch):
    dataset_id = "D_PHASE5_API"
    monkeypatch.setattr(config, "MODEL_AGENT_DIR", tmp_path / "model-agent")
    frame = pd.DataFrame({"target7": [0, 1] * 300, "is_old": [0] * 600, "create_time": pd.date_range("2026-01-01", periods=600, freq="h")})
    analysis_service.DATASETS[dataset_id] = {"df": frame, "governance": pd.DataFrame(), "rules": [], "target": "target7", "segment_field": "is_old"}
    try:
        client = TestClient(app)
        created = client.post("/api/decision/loops", json={"dataset_id": dataset_id})
        assert created.status_code == 200
        loop_id = created.json()["loop_id"]
        planned = client.post(f"/api/decision/loops/{loop_id}/next", json={"dataset_id": dataset_id})
        assert planned.status_code == 200 and planned.json()["status"] == "RUNNING"
        executed = client.post(f"/api/decision/loops/{loop_id}/execute", json={"dataset_id": dataset_id})
        assert executed.status_code == 200 and executed.json()["status"] == "SUCCESS"
        detail = client.get(f"/api/decision/loops/{loop_id}", params={"dataset_id": dataset_id}).json()
        assert detail["decisions"][-1]["selected_action"]["action_type"] == "NO_ACTION"
    finally:
        analysis_service.DATASETS.pop(dataset_id, None)


def test_tool_registry_rejects_arbitrary_execution(tmp_path):
    tools = ControlledToolRegistry(DecisionToolAuditRegistry(tmp_path))
    with pytest.raises(ValidationError):
        ToolCall(tool_name="shell", arguments={"command": "whoami"})
    call = ToolCall(tool_name="get_model_state", arguments={"dataset_id": "D1", "command": "whoami"})
    with pytest.raises(ValueError, match="Unknown tool arguments"):
        tools.execute(call)
