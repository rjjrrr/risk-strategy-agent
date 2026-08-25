from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from core.json_utils import sanitize_json
from .config import MAX_AGENT_ROUNDS, MODEL_STAGES
from .registry import utc_now


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class ModelAgentStateStore:
    """Versioned state with explicit CURRENT/BEST/LAST_STABLE pointers."""

    def __init__(self, root: str | Path, dataset_id: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.dataset_id = dataset_id
        self.state_path = self.root / "model_agent_state.json"
        self.snapshots_path = self.root / "state_snapshots.json"

    def create(self, *, budget: dict[str, Any] | None = None, max_rounds: int = MAX_AGENT_ROUNDS) -> dict[str, Any]:
        state = {
            "dataset_id": self.dataset_id,
            "segment": "NEW",
            "data_state": {}, "semantic_state": {}, "hypothesis_state": {},
            "feature_state": {}, "model_state": {}, "evaluation_state": {},
            "diagnosis_state": {}, "experiment_state": {},
            "current_state_id": None, "best_state_id": None, "last_stable_state_id": None,
            "current_experiment_id": None, "round_index": 0, "max_rounds": max_rounds,
            "budget": budget or {"hypotheses": 20, "features": 20, "experiments": 6},
            "pending_human_approval": [],
            "stage_status": {stage: "NOT_STARTED" for stage in MODEL_STAGES},
            "stop_reason": None, "updated_at": utc_now(),
        }
        self.save(state)
        if not self.snapshots_path.exists():
            self.snapshots_path.write_text("[]", encoding="utf-8")
        return state

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self.create()
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> dict[str, Any]:
        state["updated_at"] = utc_now()
        clean = sanitize_json(state)
        self.state_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        return clean

    def snapshots(self) -> list[dict[str, Any]]:
        if not self.snapshots_path.exists():
            return []
        return json.loads(self.snapshots_path.read_text(encoding="utf-8"))

    def snapshot(
        self, *, parent_state_id: str | None, experiment_id: str | None,
        dataset_version: str, feature_pool_version: str, model_config_version: str,
        lr_features: list[str], lgbm_features: list[str], model_type: str,
        model_params: dict[str, Any], metrics: dict[str, Any], diagnosis: dict[str, Any] | None = None,
        is_best: bool = False, is_stable: bool = False,
    ) -> dict[str, Any]:
        row = {
            "state_id": _id("S"), "parent_state_id": parent_state_id,
            "experiment_id": experiment_id, "created_at": utc_now(),
            "dataset_version": dataset_version, "feature_pool_version": feature_pool_version,
            "model_config_version": model_config_version, "lr_features": lr_features,
            "lgbm_features": lgbm_features, "model_type": model_type,
            "model_params": model_params, "metrics": metrics, "diagnosis": diagnosis or {},
            "is_best": is_best, "is_stable": is_stable,
        }
        rows = self.snapshots()
        if is_best:
            for item in rows:
                item["is_best"] = False
        rows.append(row)
        self.snapshots_path.write_text(json.dumps(sanitize_json(rows), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        state = self.load()
        state["current_state_id"] = row["state_id"]
        if is_best:
            state["best_state_id"] = row["state_id"]
        if is_stable:
            state["last_stable_state_id"] = row["state_id"]
        self.save(state)
        return row

    def get_snapshot(self, state_id: str) -> dict[str, Any]:
        row = next((item for item in self.snapshots() if item["state_id"] == state_id), None)
        if row is None:
            raise KeyError(state_id)
        return row

    def rollback(self, state_id: str | None = None) -> dict[str, Any]:
        state = self.load()
        target = state_id or state.get("last_stable_state_id") or state.get("best_state_id")
        if not target:
            raise ValueError("No stable or best state is available for rollback")
        snapshot = self.get_snapshot(target)
        state["current_state_id"] = target
        previous = state.get("model_state", {})
        model_type = snapshot["model_type"]
        metric_key = "lr_baseline" if model_type == "LR" else "lgbm_baseline"
        model_record = {**previous.get(metric_key, {}), "metrics": snapshot["metrics"]}
        active_features = snapshot["lr_features"] if model_type == "LR" else snapshot["lgbm_features"]
        state["model_state"] = {
            **previous, "champion": model_type, metric_key: model_record,
            "baseline_features": active_features, "model_type": model_type,
            "model_params": snapshot["model_params"], "lr_features": snapshot["lr_features"],
            "lgbm_features": snapshot["lgbm_features"], "metrics": snapshot["metrics"],
        }
        state["experiment_state"]["last_rollback_at"] = utc_now()
        self.save(state)
        return snapshot
