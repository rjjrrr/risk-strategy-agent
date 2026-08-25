from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from core.counterfactual.audit import CounterfactualRegistry, FeatureCreditRegistry, HypothesisCreditRegistry
from core.decision_agent.loop import DecisionLoopManager
from core.decision_agent.registry import DecisionToolAuditRegistry
from core.decision_agent.schemas import DecisionBudget
from core.decision_agent.tools import ControlledToolRegistry
from core.feature_validation.audit import FeatureValidationRegistry
from core.model_agent.registry import FeatureRegistry, HypothesisRegistry
from core.model_agent.state import ModelAgentStateStore

from .. import config
from . import agent_chat_service, feature_validation_service, model_agent_service
from .analysis_service import DATASETS, get_dataset


def _model_root(dataset_id: str) -> Path:
    root = config.MODEL_AGENT_DIR / dataset_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def _decision_root(dataset_id: str) -> Path:
    root = _model_root(dataset_id) / "decision"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _read(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _state(dataset_id: str) -> dict[str, Any]:
    root = _model_root(dataset_id)
    state = _read(root / "model_agent_state.json", {})
    if not state:
        return {"dataset_id": dataset_id, "current_state_id": None, "best_state_id": None, "last_stable_state_id": None, "model_state": {}}
    state["active_hypotheses"] = [row.get("hypothesis_id") for row in HypothesisRegistry(root).all() if row.get("status") in {"PROPOSED", "TESTING", "SUPPORTED"}]
    return state


def _context(dataset_id: str) -> dict[str, Any]:
    ds = get_dataset(dataset_id); root = _model_root(dataset_id)
    state = _state(dataset_id); snapshots = _read(root / "state_snapshots.json", [])
    by_id = {row.get("state_id"): row for row in snapshots}
    governance = ds.get("governance")
    governance_rows = governance.to_dict("records") if hasattr(governance, "to_dict") else list(governance or [])
    validations = FeatureValidationRegistry(root).all()
    confirmed_leakage = [str(row.get("feature_id")) for row in validations if row.get("decision") == "LEAKAGE_RISK"]
    frame = ds["df"]
    from . import experiment_memory_service
    memory = experiment_memory_service.decision_context(dataset_id, {"model_type": state.get("model_state", {}).get("model_type"), "diagnosis_type": "UNKNOWN"})
    candidates = FeatureRegistry(root).all()
    try:
        prepared = []
        for feature in candidates:
            validation = feature.get("validation_result") or {}
            prepared.append({"candidate_id": feature.get("feature_id"), "action_type": "TEST_FEATURE", "feature_id": feature.get("feature_id"), "hypothesis_id": feature.get("hypothesis_id"), "model_type": "LR" if validation.get("lr_eligible", feature.get("lr_eligible", True)) else "LGBM", "feature_type": feature.get("feature_type", "UNKNOWN"), "semantic_domain": feature.get("semantic_domain", "UNKNOWN"), "validation_metrics": validation.get("metrics", {}), "novelty": validation.get("metrics", {}).get("feature_novelty", "UNKNOWN"), "cost": feature.get("estimated_cost", "LOW")})
        ranked = experiment_memory_service.rank_candidates(dataset_id, prepared) if prepared else {"items": []}
        ranking_map = {x.get("feature_id") or x.get("candidate_id"): x for x in ranked.get("items", [])}
        candidates = [{**feature, "experiment_ranking": ranking_map.get(feature.get("feature_id"), {})} for feature in candidates]
    except Exception:
        # Surrogate/memory failure must never block Phase 5 deterministic decisions.
        pass
    return {
        "model_state": {**state.get("model_state", {}), "current_state_id": state.get("current_state_id"), "best_state_id": state.get("best_state_id"), "last_stable_state_id": state.get("last_stable_state_id")},
        "current_state": by_id.get(state.get("current_state_id"), {}),
        "best_state": by_id.get(state.get("best_state_id"), {}),
        "last_stable_state": by_id.get(state.get("last_stable_state_id"), {}),
        "feature_validations": validations,
        "feature_credits": FeatureCreditRegistry(root).all(),
        "hypothesis_credits": HypothesisCreditRegistry(root).all(),
        "counterfactual_history": CounterfactualRegistry(root).all(),
        "experiment_history": _read(root / "experiment_registry.json", []),
        "data_health": {"sample_size": int(len(frame)), "minimum_sample": 500, "severe_issue": False},
        "governance": governance_rows,
        "rule_summary": list(ds.get("rules") or [])[-20:],
        "conversation_memory": [],
        "candidate_features": candidates,
        "hypotheses": HypothesisRegistry(root).all(),
        "confirmed_leakage": confirmed_leakage,
        "warnings": [],
        "experiment_memory": memory,
    }


def _validation(dataset_id: str, feature_id: str, time_field: str | None = None) -> dict:
    return feature_validation_service.run_validation(dataset_id, feature_id, time_field)


def _counterfactual(dataset_id: str, feature_id: str, model_type: str, experiment_type="FEATURE_ADD", seed=42) -> dict:
    result = feature_validation_service.run_counterfactual(dataset_id, feature_id, model_type, experiment_type=experiment_type, seed=seed, user_confirmed=True)
    result["feature_credit"] = feature_validation_service.feature_credit(dataset_id, feature_id)
    hypothesis_id = next((row.get("hypothesis_id") for row in FeatureRegistry(_model_root(dataset_id)).all() if row.get("feature_id") == feature_id), None)
    result["hypothesis_credit"] = feature_validation_service.hypothesis_credit(dataset_id, hypothesis_id) if hypothesis_id else None
    from . import experiment_memory_service
    result["memory_update"] = experiment_memory_service.refresh(dataset_id)
    return result


def _evaluate_model(dataset_id: str, state_id: str | None = None, model_type: str | None = None) -> dict:
    summary = model_agent_service.summary(dataset_id)
    model = summary.get("summary", {}); selected = (model_type or model.get("champion") or "LR").upper()
    metrics = model.get("lgbm_baseline" if selected == "LGBM" else "lr_baseline", {})
    current = model.get("lgbm_baseline" if model.get("champion") == "LGBM" else "lr_baseline", {})
    selected_auc = float(metrics.get("oot_auc") or metrics.get("metrics", {}).get("oot_auc") or 0)
    current_auc = float(current.get("oot_auc") or current.get("metrics", {}).get("oot_auc") or 0)
    return {"decision": "POSITIVE" if selected_auc > current_auc else "NEUTRAL", "model_type": selected, "metrics_before": current, "metrics_after": metrics, "baseline_state_id": state_id}


def _rollback(dataset_id: str, state_id: str | None = None) -> dict:
    return model_agent_service.rollback(dataset_id, state_id)


def _feature_credit(dataset_id: str, feature_id: str, model_type: str | None = None) -> dict:
    rows = feature_validation_service.feature_credit(dataset_id, feature_id)
    return {"items": [row for row in rows if not model_type or row.get("model_type") == model_type]}


def _hypothesis_credit(dataset_id: str, hypothesis_id: str) -> dict:
    return feature_validation_service.hypothesis_credit(dataset_id, hypothesis_id)


def _request_analysis(dataset_id: str, reason: str, focus_fields=None) -> dict:
    return {"decision": "REVIEW", "request_status": "PENDING_ANALYSIS", "dataset_id": dataset_id, "reason": reason, "focus_fields": focus_fields or []}


def _tools(dataset_id: str) -> ControlledToolRegistry:
    tools = ControlledToolRegistry(DecisionToolAuditRegistry(_decision_root(dataset_id)))
    tools.register("run_feature_validation", _validation)
    tools.register("run_lr_counterfactual", lambda dataset_id, feature_id, experiment_type="FEATURE_ADD", seed=42: _counterfactual(dataset_id, feature_id, "LR", experiment_type, seed))
    tools.register("run_lgbm_counterfactual", lambda dataset_id, feature_id, experiment_type="FEATURE_ADD", seed=42: _counterfactual(dataset_id, feature_id, "LGBM", experiment_type, seed))
    tools.register("run_feature_ablation", lambda dataset_id, feature_id, model_type, seed=42: _counterfactual(dataset_id, feature_id, model_type, "FEATURE_REMOVE", seed))
    tools.register("evaluate_model", _evaluate_model)
    tools.register("get_model_state", lambda dataset_id: _state(dataset_id))
    tools.register("rollback_state", _rollback)
    tools.register("get_feature_credit", _feature_credit)
    tools.register("get_hypothesis_credit", _hypothesis_credit)
    tools.register("request_analysis_agent", _request_analysis)
    return tools


def _llm_decider(payload: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    context_text = json.dumps(payload["context"], ensure_ascii=False, separators=(",", ":"))
    result = agent_chat_service.runtime.chat("DECISION_AGENT", [{"role": "user", "content": "Select the next controlled experiment action from this decision context."}], None, context_text)
    response = result["result"]; binding = result["binding"]; prompt = result["prompt"]
    runtime_type = response.get("runtime_type") or response.get("execution_mode") or ("MOCK" if binding.get("provider") == "MOCK" else "LLM")
    return {
        "decision": result["structured"],
        "trace": {
            "provider": binding.get("provider"), "binding": binding.get("binding_id"), "model": binding.get("model"),
            "prompt_version": prompt.get("prompt_id"), "context_id": payload.get("context_hash")[:16], "context_hash": payload.get("context_hash"),
            "latency_ms": round((time.perf_counter() - started) * 1000), "token_usage": response.get("usage", {}),
            "call_id": response.get("call_id") or response.get("id"), "runtime_type": runtime_type,
        },
    }


def manager(dataset_id: str) -> DecisionLoopManager:
    get_dataset(dataset_id)
    from . import shadow_service
    return DecisionLoopManager(_decision_root(dataset_id), dataset_id, _tools(dataset_id), context_provider=_context, state_provider=_state, llm_decider=_llm_decider, shadow_observer=lambda record,context_hash:shadow_service.observe(dataset_id,record,context_hash), shadow_reconciler=lambda decision_id,result,state_after:shadow_service.reconcile(dataset_id,decision_id,result,state_after))


def create_loop(dataset_id: str, budget: dict[str, Any] | None = None) -> dict:
    return manager(dataset_id).create(DecisionBudget.model_validate(budget or {}))


def find_dataset(loop_id: str, dataset_id: str | None = None) -> str:
    if dataset_id:
        return dataset_id
    if config.MODEL_AGENT_DIR.exists():
        for path in config.MODEL_AGENT_DIR.glob("*/decision/decision_loops.json"):
            if any(row.get("loop_id") == loop_id for row in _read(path, [])):
                return path.parents[1].name
    raise KeyError(loop_id)


def get_loop(loop_id: str, dataset_id: str | None = None) -> dict:
    did = find_dataset(loop_id, dataset_id); mgr = manager(did)
    return {"loop": mgr.get(loop_id), "feedback": mgr.feedback_context(loop_id), "decisions": [row for row in mgr.decisions.all() if row.get("loop_id") == loop_id], "plans": [row for row in mgr.plans.all() if row.get("decision_id") in {item.get("decision_id") for item in mgr.decisions.all() if item.get("loop_id") == loop_id}], "approvals": [row for row in mgr.approvals.all() if row.get("loop_id") == loop_id]}
