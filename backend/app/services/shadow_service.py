from __future__ import annotations
import json,time,uuid
from pathlib import Path
from typing import Any
from core.experiment_memory.audit import ExperimentMemoryRegistry
from core.shadow.manager import ShadowManager
from core.surrogate.trainer import SurrogateTrainer
from . import experiment_memory_service

def root(dataset_id):
    p=experiment_memory_service.root(dataset_id)/"shadow";p.mkdir(parents=True,exist_ok=True);return p
def manager(dataset_id):return ShadowManager(root(dataset_id))
def observe(dataset_id,record,context_hash):
    return manager(dataset_id).record_round(loop_id=record["loop_id"],decision=record,context_hash=context_hash,dataset_id=dataset_id,dataset_version=experiment_memory_service.dataset_version(dataset_id),memory_source="REAL")
def reconcile(dataset_id,decision_id,result,state_after=None):return manager(dataset_id).reconcile(decision_id=decision_id,result=result,state_after=state_after,memory_source="REAL")
def real_memory(dataset_id):
    experiment_memory_service.refresh(dataset_id);return [x for x in ExperimentMemoryRegistry(experiment_memory_service.memory_root(dataset_id)).all() if x.get("source","REAL")=="REAL"]
def status(dataset_id):
    mgr=manager(dataset_id);memory=real_memory(dataset_id);checkpoint=mgr.checkpoints(memory);evaluation=mgr.evaluation();gate=mgr.promotion_gate(memory,evaluation);rows=mgr.predictions.all();_ensure_checkpoint_reports(dataset_id,checkpoint,evaluation)
    return {"mode":"SHADOW","final_selection_policy":"PHASE5","shadow_only":True,**checkpoint,"real_predictions":len([x for x in rows if x.get('memory_source')=='REAL']),"actual_available":len([x for x in rows if x.get('memory_source')=='REAL' and x.get('status')=='EVALUATED']),"evaluation":evaluation,"promotion_gate":gate}
def predictions(dataset_id,limit=200):return manager(dataset_id).predictions.all()[-max(1,min(limit,1000)):]
def prediction(dataset_id,shadow_id):
    row=manager(dataset_id).predictions.get(shadow_id)
    if not row:raise KeyError(shadow_id)
    return row
def authorize_comparison(dataset_id,shadow_id,user_confirmed=False):return manager(dataset_id).authorize_comparison(shadow_id,user_confirmed)
def evaluation(dataset_id):return manager(dataset_id).evaluation()
def errors(dataset_id):
    mgr=manager(dataset_id);return {"items":sorted(mgr.errors.all(),key=lambda x:float(x.get('absolute_error',{}).get('auc') or 0),reverse=True),"breakdown":mgr.error_breakdown()}
def checkpoints(dataset_id):return manager(dataset_id).checkpoints(real_memory(dataset_id))
def models(dataset_id):return manager(dataset_id).models.all()
def retrain(dataset_id,user_confirmed=False):
    if not user_confirmed:raise ValueError("SHADOW_RETRAIN_REQUIRES_USER_CONFIRMATION")
    memory=real_memory(dataset_id);checkpoint=manager(dataset_id).checkpoints(memory)
    if checkpoint["real_usable"]<30:return {**checkpoint,"status":"INSUFFICIENT_DATA","reason":"REAL_SURROGATE_INSUFFICIENT_DATA"}
    prior=manager(dataset_id).models.all();last_count=max([int(x.get('training_count') or 0) for x in prior] or [0]);increment=checkpoint["real_usable"]-last_count;required=10 if checkpoint["real_usable"]<100 else 20
    if prior and increment<required:raise ValueError(f"RETRAIN_INCREMENT_REQUIRED:{required}")
    started=time.perf_counter();model=SurrogateTrainer(root(dataset_id)/"models").train(memory,user_confirmed=True);role="CHALLENGER" if prior else "CURRENT_SHADOW_MODEL";state={"state_id":f"SMS_{uuid.uuid4().hex[:10]}","surrogate_id":model["surrogate_id"],"role":role,"training_count":model["training_count"],"status":model["status"],"metrics":model.get("metrics",{}),"memory_source":"REAL"};manager(dataset_id).models.add(state);_checkpoint_report(dataset_id,checkpoint["real_usable"],model);return {"model":model,"shadow_state":state,"performance_ms":{"retrain":round((time.perf_counter()-started)*1000,3)}}
def promote(dataset_id,surrogate_id,user_confirmed=False):
    if not user_confirmed:raise ValueError("SHADOW_PROMOTION_REQUIRES_USER_CONFIRMATION")
    gate=manager(dataset_id).promotion_gate(real_memory(dataset_id))
    if not gate["passed"]:raise ValueError("REAL_PROMOTION_GATE_NOT_PASSED")
    return {"surrogate_id":surrogate_id,"status":"ACTIVE_CANDIDATE","mode":"SHADOW","phase7a_can_affect_final":False,"message":"Promotion to final ranking is disabled in Phase7A"}
def _checkpoint_report(dataset_id,count,model):
    threshold=100 if count>=100 else 30 if count>=30 else None
    if not threshold:return
    path=root(dataset_id)/f"REAL_SURROGATE_{threshold}_REPORT.md";path.write_text(f"# Real Surrogate {threshold} Report\n\nREAL usable: {count}\n\nStatus: {model.get('status')}\n\nMetrics: `{json.dumps(model.get('metrics',{}),ensure_ascii=False)}`\n",encoding="utf-8")
def _ensure_checkpoint_reports(dataset_id,checkpoint,evaluation):
    count=checkpoint["real_usable"]
    for threshold in (30,100):
        if count>=threshold:
            path=root(dataset_id)/f"REAL_SURROGATE_{threshold}_REPORT.md"
            if not path.exists():
                path.write_text(f"# Real Surrogate {threshold} Report\n\nREAL usable: {count}\n\nMode: SHADOW\n\nEvaluation: `{json.dumps(evaluation,ensure_ascii=False)}`\n",encoding="utf-8")
