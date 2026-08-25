from __future__ import annotations
import time,uuid
from collections import defaultdict
from pathlib import Path
import numpy as np
from core.surrogate.diagnostics import classification_metrics,ranking_metrics,regression_metrics
from .audit import PredictionErrorRegistry,ShadowModelStateRegistry,ShadowPredictionRegistry
from .schemas import PredictionErrorRecord,ShadowPredictionRecord

class ShadowManager:
    """Observational dual-track log; never returns or mutates final selection."""
    def __init__(self,root:str|Path):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.predictions=ShadowPredictionRegistry(self.root);self.errors=PredictionErrorRegistry(self.root);self.models=ShadowModelStateRegistry(self.root)
    def record_round(self,*,loop_id,decision,context_hash,dataset_id,dataset_version="UNKNOWN",segment="NEW",memory_source="REAL"):
        started=time.perf_counter();candidates=list(decision.get("candidate_actions") or []);selected=decision.get("selected_action") or {};selected_key=self._key(selected)
        valid_indices=[i for i,x in enumerate(candidates) if (x.get("surrogate_prediction") or {}).get("positive_probability") is not None and not (x.get("surrogate_prediction") or {}).get("fallback")]
        shadow_order=sorted(valid_indices,key=lambda i:-float(candidates[i]["surrogate_prediction"]["positive_probability"]));shadow_rank={index:rank+1 for rank,index in enumerate(shadow_order)};output=[]
        for index,candidate in enumerate(candidates):
            prediction=candidate.get("surrogate_prediction") or {};key=self._key(candidate);selected_by=key==selected_key;valid=index in valid_indices;srank=shadow_rank.get(index)
            status="SELECTED_BY_PHASE5" if selected_by else "OOD" if prediction.get("out_of_distribution") else "NOT_SELECTED" if valid else "INVALID"
            row=ShadowPredictionRecord(shadow_id=f"SH_{uuid.uuid4().hex[:12]}",decision_loop_id=loop_id,decision_id=decision["decision_id"],candidate_id=key,dataset_id=dataset_id,dataset_version=dataset_version,segment=segment,feature_id=(candidate.get("feature_ids") or [None])[0],hypothesis_id=candidate.get("hypothesis_id"),feature_type=candidate.get("feature_type","UNKNOWN"),semantic_domain=candidate.get("semantic_domain","UNKNOWN"),diagnosis=decision.get("diagnosis","UNKNOWN"),model_type=candidate.get("model_type") or "UNKNOWN",action_type=candidate.get("action_type"),phase5_rank=index+1,phase5_priority=float(candidate.get("priority") or 0),shadow_rank=srank,surrogate_id=prediction.get("surrogate_id"),surrogate_version=prediction.get("surrogate_version"),training_dataset_hash=prediction.get("training_dataset_hash"),positive_probability=prediction.get("positive_probability"),expected_delta_auc=prediction.get("expected_delta_auc"),expected_delta_ks=prediction.get("expected_delta_ks"),expected_delta_lift10=prediction.get("expected_delta_lift10"),uncertainty="HIGH" if prediction.get("out_of_distribution") else prediction.get("uncertainty","HIGH"),out_of_distribution=bool(prediction.get("out_of_distribution")),meta_feature_hash=prediction.get("feature_vector_hash"),context_hash=context_hash,execution_selected_by_phase5=selected_by,selection_probability=1.0 if selected_by else 0.0,execution_reason=selected.get("reason","") if selected_by else "NOT_SELECTED_BY_PHASE5",status=status,backend_final_candidate_id=selected_key,disagreement="HIGH" if srank and abs(index+1-srank)>=2 else "LOW",memory_source=memory_source)
            output.append(self.predictions.add(row.model_dump()))
        return {"items":output,"final_selected_candidate":selected_key,"final_policy":"PHASE5","performance_ms":round((time.perf_counter()-started)*1000,3)}
    def reconcile(self,*,decision_id,result,state_after=None,memory_source="REAL"):
        started=time.perf_counter();rows=[x for x in self.predictions.all() if x.get("decision_id")==decision_id and x.get("execution_selected_by_phase5")]
        actual=str(result.get("decision") or result.get("counterfactual_decision") or "FAILED");delta=result.get("delta_metrics") or {};count=0
        for row in rows:
            updated=self.predictions.update(row["shadow_id"],status="EVALUATED",actual_decision=actual,actual_delta_auc=float(delta.get("delta_oot_auc") or 0),actual_delta_ks=float(delta.get("delta_oot_ks") or 0),actual_delta_lift10=float(delta.get("delta_lift10") if delta.get("delta_lift10") is not None else delta.get("delta_lift_10") or 0),actual_stability="UNSTABLE" if actual=="UNSTABLE" else "STABLE",actual_credit=result.get("feature_credit") or {},actual_hypothesis_credit=result.get("hypothesis_credit") or {},experiment_id=result.get("experiment_id"),state_after=state_after,runtime_seconds=float(result.get("runtime_seconds") or 0),memory_source=memory_source);self._error(updated);count+=1
        return {"reconciled":count,"performance_ms":round((time.perf_counter()-started)*1000,3)}
    def authorize_comparison(self,shadow_id,user_confirmed=False):
        if not user_confirmed:raise ValueError("COMPARISON_EXPERIMENT_REQUIRES_HUMAN_CONFIRMATION")
        row=self.predictions.get(shadow_id)
        if not row:raise KeyError(shadow_id)
        if row.get("execution_selected_by_phase5"):raise ValueError("CANDIDATE_ALREADY_SELECTED_BY_PHASE5")
        return self.predictions.update(shadow_id,status="EXPERIMENT_RUNNING",execution_reason="HUMAN_COMPARISON_CANDIDATE",selection_probability=0.0)
    def reconcile_shadow(self,shadow_id,result,state_after=None,memory_source="REAL"):
        row=self.predictions.get(shadow_id)
        if not row or row.get("status")!="EXPERIMENT_RUNNING":raise ValueError("SHADOW_COMPARISON_NOT_AUTHORIZED")
        actual=str(result.get("decision") or "FAILED");delta=result.get("delta_metrics") or {};updated=self.predictions.update(shadow_id,status="EVALUATED",actual_decision=actual,actual_delta_auc=float(delta.get("delta_oot_auc") or 0),actual_delta_ks=float(delta.get("delta_oot_ks") or 0),actual_delta_lift10=float(delta.get("delta_lift10") or 0),experiment_id=result.get("experiment_id"),state_after=state_after,memory_source=memory_source);self._error(updated);return updated
    def _error(self,row):
        if row.get("positive_probability") is None:
            return None
        p=float(row.get("positive_probability") or 0);truth=row.get("actual_decision")=="POSITIVE";pa=float(row.get("expected_delta_auc") or 0);aa=float(row.get("actual_delta_auc") or 0);pk=float(row.get("expected_delta_ks") or 0);ak=float(row.get("actual_delta_ks") or 0);pl=float(row.get("expected_delta_lift10") or 0);al=float(row.get("actual_delta_lift10") or 0)
        error=PredictionErrorRecord(error_id=f"PE_{uuid.uuid4().hex[:12]}",shadow_id=row["shadow_id"],surrogate_version=row.get("surrogate_version"),predicted={"positive_probability":p,"delta_auc":pa,"delta_ks":pk,"delta_lift10":pl},actual={"positive":truth,"decision":row.get("actual_decision"),"delta_auc":aa,"delta_ks":ak,"delta_lift10":al},absolute_error={"probability":abs(p-float(truth)),"auc":abs(pa-aa),"ks":abs(pk-ak),"lift10":abs(pl-al)},direction_error=(pa>=0)!=(aa>=0),classification_error=(p>=.5)!=truth,out_of_distribution=bool(row.get("out_of_distribution")),feature_type=row.get("feature_type","UNKNOWN"),semantic_domain=row.get("semantic_domain","UNKNOWN"),model_type=row.get("model_type","UNKNOWN"),diagnosis=row.get("diagnosis","UNKNOWN"),action_type=row.get("action_type","UNKNOWN"));return self.errors.add(error.model_dump())
    def evaluation(self,memory_source="REAL"):
        rows=[x for x in self.predictions.all() if x.get("status")=="EVALUATED" and x.get("memory_source")==memory_source];metrics={k:self._metrics(v) for k,v in {"ALL_HISTORY":rows,"RECENT_30":rows[-30:],"RECENT_50":rows[-50:]}.items()};all_auc=metrics["ALL_HISTORY"].get("classification",{}).get("auc");recent=metrics["RECENT_30"].get("classification",{}).get("auc");drift=all_auc is not None and recent is not None and recent<all_auc-.10
        return {"real_usable":len(rows),"windows":metrics,"performance_drift":bool(drift),"drift_status":"SURROGATE_PERFORMANCE_DRIFT" if drift else "STABLE_OR_INSUFFICIENT","head_to_head":self.head_to_head(rows)}
    def _metrics(self,rows):
        if not rows:return {"count":0}
        y=[x.get("actual_decision")=="POSITIVE" for x in rows];p=[float(x.get("positive_probability") or 0) for x in rows];actual=[float(x.get("actual_delta_auc") or 0) for x in rows];pred=[float(x.get("expected_delta_auc") or 0) for x in rows];groups=defaultdict(list)
        for x in rows:groups[x.get("decision_id")].append(x)
        comparable=[g for g in groups.values() if len(g)>=3 and all(x.get("actual_decision") is not None for x in g)];ranking={}
        if comparable:
            sm=[];pm=[]
            for g in comparable:
                gy=[x.get("actual_decision")=="POSITIVE" for x in g];gain=[float(x.get("actual_delta_auc") or 0) for x in g];sm.append(ranking_metrics(gy,gain,[-int(x.get("shadow_rank") or 999) for x in g]));pm.append(ranking_metrics(gy,gain,[-int(x.get("phase5_rank") or 999) for x in g]))
            ranking={"rounds":len(comparable),"shadow_ndcg_at_10":float(np.mean([x["ndcg_at_10"] for x in sm])),"phase5_ndcg_at_10":float(np.mean([x["ndcg_at_10"] for x in pm]))}
        classification=classification_metrics(y,p) if len(set(y))>1 else {"auc":None,"positive_rate":float(np.mean(y)),"brier_score":float(np.mean((np.asarray(p)-np.asarray(y))**2))}
        regression=regression_metrics(actual,pred) if len(rows)>1 else {"mae":abs(actual[0]-pred[0]),"rmse":abs(actual[0]-pred[0]),"r2":None,"spearman":0.0,"pearson":0.0}
        return {"count":len(rows),"classification":classification,"regression":regression,"ranking":ranking,"ood_rate":float(np.mean([bool(x.get("out_of_distribution")) for x in rows])),"prediction_distribution":{"mean":float(np.mean(p)),"std":float(np.std(p)),"min":float(np.min(p)),"max":float(np.max(p))},"expected_gain_distribution":{"mean":float(np.mean(pred)),"std":float(np.std(pred)),"min":float(np.min(pred)),"max":float(np.max(pred))}}
    def head_to_head(self,rows):
        groups=defaultdict(list);wins={"surrogate_wins":0,"phase5_wins":0,"tie":0}
        for x in rows:groups[x.get("decision_id")].append(x)
        for group in groups.values():
            if len(group)<3:continue
            positive=[x for x in group if x.get("actual_decision")=="POSITIVE"]
            if not positive:wins["tie"]+=1;continue
            s=min(int(x.get("shadow_rank") or 999) for x in positive);p=min(int(x.get("phase5_rank") or 999) for x in positive);wins["surrogate_wins" if s<p else "phase5_wins" if p<s else "tie"]+=1
        return wins
    def checkpoints(self,real_memory,fixture_mode=False):
        allowed={"REAL","TEST_FIXTURE"} if fixture_mode else {"REAL"};real=[x for x in real_memory if x.get("source","REAL") in allowed];usable=[x for x in real if x.get("counterfactual_decision") in {"POSITIVE","NEUTRAL","NEGATIVE","UNSTABLE"}];count=len(usable)
        return {"real_total":len(real),"real_usable":count,"next_checkpoint":30 if count<30 else 100 if count<100 else None,"progress":{"to_30":min(count,30),"to_100":min(count,100)},"status":"INSUFFICIENT_DATA" if count<30 else "REAL_EXPERIMENTAL" if count<100 else "REAL_ACTIVE_CANDIDATE_EVALUATION"}
    def promotion_gate(self,real_memory,evaluation=None,fixture_mode=False):
        checkpoint=self.checkpoints(real_memory,fixture_mode=fixture_mode);evaluation=evaluation or self.evaluation();m=evaluation.get("windows",{}).get("ALL_HISTORY",{});auc=m.get("classification",{}).get("auc") or 0;sp=m.get("regression",{}).get("spearman") or 0;rank=m.get("ranking",{});passed=checkpoint["real_usable"]>=100 and (auc>=.60 or sp>=.20) and rank.get("shadow_ndcg_at_10",0)>0 and rank.get("shadow_ndcg_at_10",0)>=rank.get("phase5_ndcg_at_10",1) and not evaluation.get("performance_drift")
        return {"status":"ACTIVE_CANDIDATE" if passed else "REAL_SURROGATE_NOT_USEFUL" if checkpoint["real_usable"]>=100 else checkpoint["status"],"passed":passed,"phase7a_can_affect_final":False,"reasons":{"count":checkpoint["real_usable"],"auc":auc,"spearman":sp,"ranking":rank,"drift":evaluation.get("performance_drift")}}
    def error_breakdown(self):
        rows=self.errors.all();output={}
        for field in ("feature_type","semantic_domain","model_type","diagnosis","action_type"):
            groups=defaultdict(list)
            for x in rows:groups[str(x.get(field) or "UNKNOWN")].append(x)
            output[field]={key:{"count":len(items),"mae_auc":float(np.mean([x["absolute_error"]["auc"] for x in items])),"error_rate":float(np.mean([x["classification_error"] for x in items]))} for key,items in groups.items()}
        return output
    @staticmethod
    def _key(candidate):return str(candidate.get("candidate_id") or (candidate.get("feature_ids") or [candidate.get("action_type") or "UNKNOWN"])[0])
