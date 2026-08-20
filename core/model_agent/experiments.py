from __future__ import annotations

import uuid
from typing import Any

from .evaluation import Evaluator
from .registry import ExperimentRegistry, utc_now
from .state import ModelAgentStateStore


class ExperimentManager:
    def __init__(self, registry: ExperimentRegistry, state_store: ModelAgentStateStore, evaluator: Evaluator | None = None):
        self.registry=registry; self.state_store=state_store; self.evaluator=evaluator or Evaluator()

    def start(self, experiment_type: str, hypothesis_id: str | None, description: str, changes: dict[str,Any], model_type: str, params_before=None, params_after=None) -> dict[str,Any]:
        duplicate=self.registry.duplicate(experiment_type,changes,model_type)
        if duplicate: raise ValueError(f"DUPLICATE_EXPERIMENT:{duplicate['experiment_id']}")
        state=self.state_store.load(); row={"experiment_id":f"E_{uuid.uuid4().hex[:10]}","parent_state_id":state.get("current_state_id"),"experiment_type":experiment_type,"hypothesis_id":hypothesis_id,"description":description,"changes":changes,"added_features":changes.get("added_features",[]),"removed_features":changes.get("removed_features",[]),"transformed_features":changes.get("transformed_features",[]),"model_type":model_type,"model_params_before":params_before or {},"model_params_after":params_after or {},"metrics_before":{},"metrics_after":{},"diagnosis":[],"decision":"RUNNING","rollback_state_id":None,"finished_at":None}
        self.registry.add(row); state["current_experiment_id"]=row["experiment_id"]; self.state_store.save(state); return row

    def finish(self, experiment_id: str, before: dict[str,Any] | None, after: dict[str,Any], *, snapshot_args: dict[str,Any], diagnosis=None, confirmed_leakage=False, core_feature_psi=0.0) -> dict[str,Any]:
        result=self.evaluator.decide(before,after,confirmed_leakage=confirmed_leakage,core_feature_psi=core_feature_psi)
        accepted=result["decision"].startswith("ACCEPT"); state=self.state_store.load()
        snapshot=self.state_store.snapshot(parent_state_id=state.get("current_state_id"),experiment_id=experiment_id,metrics=after,diagnosis={"items":diagnosis or []},is_best=accepted,is_stable=accepted,**snapshot_args)
        rollback_id=None
        if not accepted:
            target=state.get("last_stable_state_id") or state.get("best_state_id")
            if target: self.state_store.rollback(target); rollback_id=target
        row=self.registry.update(experiment_id,metrics_before=before or {},metrics_after=after,diagnosis=diagnosis or [],decision=result["decision"],decision_reason=result["reason"],rollback_state_id=rollback_id,finished_at=utc_now(),created_state_id=snapshot["state_id"])
        current=self.state_store.load(); current["current_experiment_id"]=None; self.state_store.save(current); return row
