from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .approval import HumanApprovalManager
from .diagnosis import DiagnosisAgent
from .evaluation import Evaluator
from .experiments import ExperimentManager
from .features import FeatureGenerator
from .hypothesis import HypothesisAgent
from .models import ModelTrainer, temporal_split
from .planner import PlannerAgent
from .registry import ApprovalRegistry, DiagnosisRegistry, ExperimentRegistry, FeatureRegistry, HypothesisRegistry
from .semantic import SemanticAnalysisAgent
from .state import ModelAgentStateStore
from .validation import CheapValidator, select_feature_pools


class ModelAgentOrchestrator:
    def __init__(self, root: str | Path, dataset_id: str):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True); self.dataset_id=dataset_id
        self.state_store=ModelAgentStateStore(self.root,dataset_id)
        self.hypotheses=HypothesisRegistry(self.root); self.features=FeatureRegistry(self.root); self.experiments=ExperimentRegistry(self.root)
        self.diagnoses=DiagnosisRegistry(self.root); self.approvals=ApprovalRegistry(self.root)
        self.trainer=ModelTrainer(self.root/"models"); self.evaluator=Evaluator(); self.planner=PlannerAgent()

    @staticmethod
    def _json_default(value):
        if hasattr(value,"item"): return value.item()
        if isinstance(value,(pd.Timestamp,np.datetime64)): return str(value)
        raise TypeError(f"Not JSON serializable: {type(value).__name__}")

    @classmethod
    def _json_safe(cls,value):
        if isinstance(value,dict): return {str(k):cls._json_safe(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)): return [cls._json_safe(v) for v in value]
        if hasattr(value,"item"):
            value=value.item()
        if isinstance(value,(pd.Timestamp,np.datetime64)): return str(value)
        if isinstance(value,float) and not np.isfinite(value): return None
        return value

    def _save_json(self,name,data): (self.root/name).write_text(json.dumps(self._json_safe(data),ensure_ascii=False,indent=2,default=self._json_default),encoding="utf-8")

    @staticmethod
    def _new_data(df: pd.DataFrame, target: str, segment_field: str) -> pd.DataFrame:
        if target!="target7" or segment_field!="is_old": raise ValueError("V1 fixed contract requires target7 and is_old")
        data=df[(df[segment_field]==0)&pd.to_numeric(df[target],errors="coerce").isin([0,1])].copy()
        data[target]=pd.to_numeric(data[target],errors="coerce").astype(int); return data

    @staticmethod
    def _time_field(data: pd.DataFrame, selected: str | None = None) -> str:
        if selected and selected in data: return selected
        for field in data.columns:
            if any(token in field.lower() for token in ("apply_time","application_date","create_time","register_time")) and pd.to_datetime(data[field],errors="coerce").notna().mean()>=.7: return field
        raise ValueError("NEW Model Agent requires an application time field for OOT")

    def run_initial(self, df: pd.DataFrame, governance: pd.DataFrame, rules: list[dict[str,Any]], application_time_field: str | None = None) -> dict[str,Any]:
        state=self.state_store.create(); data=self._new_data(df,"target7","is_old"); time_field=self._time_field(data,application_time_field)
        state["data_state"]={"rows":len(data),"target":"target7","segment_field":"is_old","time_field":time_field,"dataset_version":"D1"}; state["stage_status"]["semantic_analysis"]="RUNNING"; self.state_store.save(state)
        semantics=SemanticAnalysisAgent().analyze(data,governance,rules); self._save_json("semantic_state.json",semantics); state=self.state_store.load(); state["semantic_state"]={"count":len(semantics),"path":"semantic_state.json"}; state["stage_status"]["semantic_analysis"]="SUCCESS"; self.state_store.save(state)
        hypothesis_rows=HypothesisAgent(self.hypotheses).propose(semantics,rules); state=self.state_store.load(); state["hypothesis_state"]={"count":len(hypothesis_rows)}; state["stage_status"]["hypothesis"]="SUCCESS"; self.state_store.save(state)
        generated=[]; generator=FeatureGenerator(self.features)
        for hypothesis in hypothesis_rows: generated.extend(generator.generate(data,hypothesis))
        state=self.state_store.load(); state["feature_state"]={"generated":len(generated)}; state["stage_status"]["feature_engineering"]="SUCCESS"; self.state_store.save(state)
        dev_idx,oot_idx=temporal_split(data,time_field); dev_mask=pd.Series(data.index.isin(dev_idx),index=data.index); oot_mask=pd.Series(data.index.isin(oot_idx),index=data.index)
        governed={row["field"]:row for row in semantics}; safe_raw=[field for field,row in governed.items() if field in data and row["governance_decision"]=="KEEP" and row["semantic_role"] not in {"DATETIME","IDENTIFIER","POST_LOAN_FEATURE","SUSPECT_LEAKAGE","EXISTING_MODEL"} and field not in {"target7","is_old"}]
        safe_raw=safe_raw[:30]; existing=data[safe_raw].select_dtypes(include=np.number)
        validator=CheapValidator(); validated=[]
        for feature in generated:
            series=generator.rebuild(data,feature); result=validator.validate(feature["feature_name"],series,data["target7"],dev_mask,oot_mask,existing)
            lr_ok=result["status"] in {"PROMISING","EXPLORATORY"} and result["psi"]<.1 and result["max_existing_spearman"]<=.95
            lgbm_ok=result["status"]!="REJECTED" and result["psi"]<.25
            feature=self.features.update(feature["feature_id"],validation_result=result,status="VALIDATED" if result["status"]!="REJECTED" else "REJECTED",lr_eligible=lr_ok,lgbm_eligible=lgbm_ok); validated.append(feature)
            data[feature["feature_name"]]=series
        lr_new,lgbm_new=select_feature_pools(validated); state=self.state_store.load(); state["feature_state"].update(validated=sum(x["status"]!="REJECTED" for x in validated),lr_candidates=lr_new,lgbm_candidates=lgbm_new); state["stage_status"]["cheap_validation"]="SUCCESS"; self.state_store.save(state)
        baseline_features=safe_raw or [field for field in data.select_dtypes(include=np.number).columns if field not in {"target7","is_old"}][:10]
        x=data[baseline_features]; y=data["target7"]
        lr=self.trainer.train("LR",x.loc[dev_idx],y.loc[dev_idx],x.loc[oot_idx],y.loc[oot_idx],"lr_baseline")
        lgbm=self.trainer.train("LGBM",x.loc[dev_idx],y.loc[dev_idx],x.loc[oot_idx],y.loc[oot_idx],"lgbm_baseline")
        lr_gate=self.evaluator.hard_gate(lr["metrics"])[0]; lgbm_gate=self.evaluator.hard_gate(lgbm["metrics"])[0]
        champion="LGBM" if lgbm_gate and lgbm["metrics"]["oot_auc"]>=lr["metrics"]["oot_auc"] and lgbm["metrics"]["oot_ks"]>=lr["metrics"]["oot_ks"] else "LR"
        lr_snapshot=self.state_store.snapshot(parent_state_id=None,experiment_id=None,dataset_version="D1",feature_pool_version="F_BASE",model_config_version="LR_BASE",lr_features=baseline_features,lgbm_features=baseline_features,model_type="LR",model_params={"penalty":"l2"},metrics=lr["metrics"],is_best=champion=="LR",is_stable=lr_gate)
        lgbm_snapshot=self.state_store.snapshot(parent_state_id=lr_snapshot["state_id"],experiment_id=None,dataset_version="D1",feature_pool_version="F_BASE",model_config_version="LGBM_BASE",lr_features=baseline_features,lgbm_features=baseline_features,model_type="LGBM",model_params={},metrics=lgbm["metrics"],is_best=champion=="LGBM",is_stable=lgbm_gate)
        state=self.state_store.load(); state["model_state"]={"champion":champion,"lr_baseline":{k:v for k,v in lr.items() if k!="pipeline"},"lgbm_baseline":{k:v for k,v in lgbm.items() if k!="pipeline"},"baseline_features":baseline_features}; state["stage_status"]["model_baseline"]="SUCCESS"; self.state_store.save(state)
        champion_snapshot=lr_snapshot if champion=="LR" else lgbm_snapshot
        state=self.state_store.load(); state["current_state_id"]=champion_snapshot["state_id"]
        if champion_snapshot.get("is_stable"): state["last_stable_state_id"]=champion_snapshot["state_id"]
        self.state_store.save(state)
        diagnoses=DiagnosisAgent(self.diagnoses).diagnose(lgbm["metrics"] if champion=="LGBM" else lr["metrics"],feature_validations=[x.get("validation_result",{}) for x in validated]); state=self.state_store.load(); state["diagnosis_state"]={"count":len(diagnoses)}; state["stage_status"]["diagnosis"]="SUCCESS"; self.state_store.save(state)
        summary={"dataset_id":self.dataset_id,"segment":"NEW","semantics":len(semantics),"hypotheses":len(hypothesis_rows),"generated_features":len(generated),"validated_features":sum(x["status"]!="REJECTED" for x in validated),"lr_baseline":lr["metrics"],"lgbm_baseline":lgbm["metrics"],"champion":champion,"current_state_id":self.state_store.load()["current_state_id"],"best_state_id":self.state_store.load()["best_state_id"],"last_stable_state_id":self.state_store.load()["last_stable_state_id"],"diagnoses":diagnoses}
        self._save_json("model_summary.json",summary); return summary

    def run_next_experiment(self, df: pd.DataFrame) -> dict[str,Any]:
        state=self.state_store.load(); stop=self.planner.stop_reason(state,self.experiments.all(),high_confidence_remaining=any(x.get("confidence")=="HIGH" and x.get("status")=="PROPOSED" for x in self.hypotheses.all()))
        if stop: state["stop_reason"]=stop; self.state_store.save(state); return {"action":"STOP","reason":stop}
        plan=self.planner.choose(self.hypotheses.all(),self.experiments.all(),state["budget"],self.diagnoses.all())
        if plan["action"]!="RUN_EXPERIMENT": return plan
        hypothesis=self.hypotheses.get(plan["hypothesis_id"]); candidates=[x for x in self.features.all() if x.get("hypothesis_id")==hypothesis["hypothesis_id"] and x.get("status")!="REJECTED"]
        if not candidates: self.hypotheses.update(hypothesis["hypothesis_id"],status="REJECTED"); return {"action":"STOP","reason":"NO_VALIDATED_FEATURE_FOR_HYPOTHESIS"}
        feature=candidates[0]; data=self._new_data(df,"target7","is_old"); time_field=state["data_state"]["time_field"]; data[feature["feature_name"]]=FeatureGenerator.rebuild(data,feature); dev_idx,oot_idx=temporal_split(data,time_field)
        baseline=state["model_state"]; model_type=baseline["champion"]; base_metrics=baseline["lr_baseline" if model_type=="LR" else "lgbm_baseline"]["metrics"]; features=list(baseline["baseline_features"])+[feature["feature_name"]]
        experiment=ExperimentManager(self.experiments,self.state_store,self.evaluator).start("FEATURE_ADD",hypothesis["hypothesis_id"],f"Add {feature['feature_name']}",{"added_features":[feature["feature_id"]]},model_type)
        result=self.trainer.train(model_type,data.loc[dev_idx,features],data.loc[dev_idx,"target7"],data.loc[oot_idx,features],data.loc[oot_idx,"target7"],experiment["experiment_id"])
        diagnoses=DiagnosisAgent(self.diagnoses).diagnose(result["metrics"],feature_validations=[feature.get("validation_result",{})],related_experiment=experiment["experiment_id"])
        finished=ExperimentManager(self.experiments,self.state_store,self.evaluator).finish(experiment["experiment_id"],base_metrics,result["metrics"],snapshot_args={"dataset_version":"D1","feature_pool_version":f"F_{experiment['experiment_id']}","model_config_version":f"M_{model_type}","lr_features":features if model_type=="LR" else baseline["baseline_features"],"lgbm_features":features if model_type=="LGBM" else baseline["baseline_features"],"model_type":model_type,"model_params":{}},diagnosis=diagnoses)
        self.hypotheses.update(hypothesis["hypothesis_id"],status="SUPPORTED" if finished["decision"].startswith("ACCEPT") else "REJECTED",related_experiments=[experiment["experiment_id"]]); self.features.update(feature["feature_id"],status="EXPERIMENTAL")
        state=self.state_store.load(); state["round_index"]+=1; state["budget"]["experiments"]-=1; state["stage_status"]["experiments"]="SUCCESS"; state["stage_status"]["evaluation"]="SUCCESS"; self.state_store.save(state); return finished

    def approval_manager(self): return HumanApprovalManager(self.approvals,self.state_store)
