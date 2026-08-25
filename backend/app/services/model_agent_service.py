from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.model_agent.orchestrator import ModelAgentOrchestrator
from core.model_agent.config import MODEL_METRICS_VERSION
from core.model_agent.registry import utc_now
from core.counterfactual.audit import FeatureCreditRegistry, HypothesisCreditRegistry
from core.feature_validation.audit import FeatureValidationRegistry

from .. import config
from ..json_safe import sanitize_json
from .analysis_service import get_dataset


def _clean(value: Any) -> Any:
    return sanitize_json(value)


def root_for(dataset_id: str) -> Path:
    root = config.MODEL_AGENT_DIR / dataset_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def agent(dataset_id: str) -> ModelAgentOrchestrator:
    get_dataset(dataset_id)
    return ModelAgentOrchestrator(root_for(dataset_id), dataset_id)


def run_initial(dataset_id: str, application_time_field: str | None = None) -> dict[str, Any]:
    ds = get_dataset(dataset_id)
    if ds.get("governance") is None:
        raise ValueError("请先完成字段治理，再启动 NEW 客群模型实验 Agent")
    result = agent(dataset_id).run_initial(
        ds["df"], ds["governance"], ds.get("rules", []), application_time_field
    )
    return _clean(result)


def run_next(dataset_id: str) -> dict[str, Any]:
    ds = get_dataset(dataset_id)
    return _clean(agent(dataset_id).run_next_experiment(ds["df"]))


def stop(dataset_id: str, reason: str) -> dict[str, Any]:
    a = agent(dataset_id)
    state = a.state_store.load()
    state["stop_reason"] = reason or "HUMAN_STOP"
    state["stage_status"]["experiments"] = "STOPPED"
    a.state_store.save(state)
    return _clean(state)


def rollback(dataset_id: str, state_id: str | None = None) -> dict[str, Any]:
    a = agent(dataset_id)
    before = a.state_store.load().get("current_state_id")
    snapshot = a.state_store.rollback(state_id)
    row = {
        "experiment_id": f"E_ROLLBACK_{len(a.experiments.all()) + 1:04d}",
        "parent_state_id": before,
        "experiment_type": "ROLLBACK",
        "hypothesis_id": None,
        "description": f"Human rollback to {snapshot['state_id']}",
        "changes": {"from_state_id": before, "to_state_id": snapshot["state_id"]},
        "added_features": [], "removed_features": [], "transformed_features": [],
        "model_type": snapshot["model_type"], "model_params_before": {},
        "model_params_after": snapshot.get("model_params", {}), "metrics_before": {},
        "metrics_after": snapshot.get("metrics", {}), "diagnosis": [],
        "decision": "ROLLBACK", "rollback_state_id": snapshot["state_id"],
        "finished_at": utc_now(),
    }
    a.experiments.add(row)
    return _clean({"snapshot": snapshot, "experiment": row})


def list_artifact(dataset_id: str, kind: str) -> list[dict[str, Any]]:
    a = agent(dataset_id)
    registries = {
        "hypotheses": a.hypotheses, "features": a.features,
        "experiments": a.experiments, "diagnoses": a.diagnoses,
        "approvals": a.approvals,
    }
    if kind not in registries:
        raise KeyError(kind)
    return _clean(registries[kind].all())


def semantics(dataset_id: str) -> list[dict[str, Any]]:
    path = root_for(dataset_id) / "semantic_state.json"
    return _clean(json.loads(path.read_text(encoding="utf-8")) if path.exists() else [])


def timeline(dataset_id: str) -> list[dict[str, Any]]:
    a = agent(dataset_id)
    rows: list[dict[str, Any]] = []
    for kind, registry, key in (
        ("HYPOTHESIS", a.hypotheses, "hypothesis_id"),
        ("FEATURE", a.features, "feature_id"),
        ("EXPERIMENT", a.experiments, "experiment_id"),
        ("DIAGNOSIS", a.diagnoses, "diagnosis_id"),
        ("APPROVAL", a.approvals, "approval_id"),
        ("FEATURE_VALIDATION", FeatureValidationRegistry(a.root), "validation_id"),
        ("FEATURE_CREDIT", FeatureCreditRegistry(a.root), "credit_id"),
        ("HYPOTHESIS_CREDIT", HypothesisCreditRegistry(a.root), "credit_id"),
    ):
        for row in registry.all():
            rows.append({"type": kind, "id": row.get(key), "time": row.get("updated_at") or row.get("finished_at") or row.get("created_at"), "status": row.get("status") or row.get("decision"), "title": row.get("description") or row.get("title") or row.get("reason") or row.get(key), "detail": row})
    return _clean(sorted(rows, key=lambda x: x.get("time") or "", reverse=True))


def summary(dataset_id: str) -> dict[str, Any]:
    a = agent(dataset_id)
    path = root_for(dataset_id) / "model_summary.json"
    model_summary = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    versions={str((model_summary.get(key) or {}).get("metrics_version") or "LEGACY") for key in ("lr_baseline","lgbm_baseline") if model_summary.get(key)}
    metrics_status="CURRENT" if versions=={MODEL_METRICS_VERSION} else "STALE_REINITIALIZATION_REQUIRED" if versions else "NOT_INITIALIZED"
    display_summary=dict(model_summary)
    if metrics_status=="STALE_REINITIALIZATION_REQUIRED":
        for key in ("lr_baseline","lgbm_baseline"):
            if key in display_summary:
                display_summary[key]={"metrics_version":"LEGACY","stale":True,"status":metrics_status}
        display_summary["champion"]=None
    return _clean({
        "state": a.state_store.load(), "summary": display_summary,
        "metrics_status":metrics_status,"required_metrics_version":MODEL_METRICS_VERSION,
        "counts": {"hypotheses": len(a.hypotheses.all()), "features": len(a.features.all()), "experiments": len(a.experiments.all()), "diagnoses": len(a.diagnoses.all()), "approvals": len(a.approvals.all())},
    })


def propose_approval(dataset_id: str, action_type: str, payload: dict[str, Any], reason: str, impact: str) -> dict[str, Any]:
    return _clean(agent(dataset_id).approval_manager().propose(action_type, payload, reason, impact))


def decide_approval(dataset_id: str, approval_id: str, decision: str, decided_by: str) -> dict[str, Any]:
    a = agent(dataset_id)
    row = a.approval_manager().decide(approval_id, decision, decided_by)
    if decision == "APPROVE":
        feature_ids = row.get("payload", {}).get("feature_ids", [])
        if row["action_type"] == "PRODUCTION_FEATURE_APPROVAL":
            for feature_id in feature_ids:
                a.features.update(feature_id, status="APPROVED", approved=True, approved_at=utc_now())
        elif row["action_type"] in {"PERMANENT_FEATURE_REMOVE", "PERMANENT_LEAKAGE_EXCLUDE"}:
            for feature_id in feature_ids:
                a.features.update(feature_id, status="REJECTED", approved_removal=True, removed_at=utc_now())
    return _clean(row)


def write_report(dataset_id: str) -> Path:
    data = summary(dataset_id); a = agent(dataset_id); state = data["state"]; model = data["summary"]
    experiments = a.experiments.all(); diagnoses = a.diagnoses.all(); approvals = a.approvals.all()
    def metric_line(name: str, metrics: dict[str, Any]) -> str:
        return f"| {name} | {metrics.get('dev_auc', '-') } | {metrics.get('oot_auc', '-') } | {metrics.get('oot_ks', '-') } | {metrics.get('train_oot_auc_gap', '-') } |"
    lines = [
        "# Risk Strategy Agent V1.0 模型实验报告", "", f"- 数据集：`{dataset_id}`", "- 客群：`NEW`", f"- 状态：`{state.get('stop_reason') or 'ACTIVE'}`", f"- 当前轮次：{state.get('round_index', 0)} / {state.get('max_rounds', 3)}", "",
        "## 模型概览", "", f"指标状态：**{data.get('metrics_status')}**", "", "| 模型 | DEV AUC | OOT AUC | OOT KS | AUC Gap |", "|---|---:|---:|---:|---:|",
        metric_line("LR", model.get("lr_baseline", {})), metric_line("LightGBM", model.get("lgbm_baseline", {})), "", f"Champion：**{model.get('champion', '-')}**", "",
        "## 状态指针", "", f"- CURRENT：`{state.get('current_state_id')}`", f"- BEST：`{state.get('best_state_id')}`", f"- LAST_STABLE：`{state.get('last_stable_state_id')}`", "",
        "## 语义、假设与特征", "", f"- 语义字段：{state.get('semantic_state', {}).get('count', 0)}", f"- 假设：{len(a.hypotheses.all())}", f"- 特征：{len(a.features.all())}", "",
        "## 实验结论", "", *(f"- `{x.get('experiment_id')}` {x.get('experiment_type')} → **{x.get('decision')}**：{x.get('decision_reason', x.get('description', ''))}" for x in experiments), "",
        "## 诊断", "", *(f"- **{x.get('diagnosis_type')}**：{x.get('evidence')}；建议：{x.get('recommended_action')}" for x in diagnoses), "",
        "## 人工审批", "", *(f"- `{x.get('approval_id')}` {x.get('action_type')}：**{x.get('status')}**" for x in approvals), "",
        "## 治理约束", "", "- 仅对 NEW 客群建模；target 固定为 target7。", "- 模型挖掘直接使用治理后的原始字段，不依赖规则挖掘结果。", "- 规则页是独立策略工具，模型结果不自动进入生产。", "- 永久删除、泄漏排除与生产特征均需人工审批。", "- 最多运行 3 轮，并保留 CURRENT / BEST / LAST_STABLE 与回滚审计。", "",
    ]
    path = root_for(dataset_id) / "model_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
