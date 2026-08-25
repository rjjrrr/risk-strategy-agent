from __future__ import annotations
from datetime import datetime,timezone
from typing import Any,Literal
from pydantic import BaseModel,Field
def utc_now():return datetime.now(timezone.utc).isoformat()
class ShadowPredictionRecord(BaseModel):
    shadow_id:str;timestamp:str=Field(default_factory=utc_now);decision_loop_id:str;decision_id:str;candidate_id:str
    dataset_id:str;dataset_version:str="UNKNOWN";segment:str="NEW";feature_id:str|None=None;feature_version:str="UNKNOWN";hypothesis_id:str|None=None
    feature_type:str="UNKNOWN";semantic_domain:str="UNKNOWN";diagnosis:str="UNKNOWN";model_type:str="UNKNOWN";action_type:str;phase5_rank:int;phase5_priority:float;shadow_rank:int|None=None
    surrogate_id:str|None=None;surrogate_version:str|None=None;training_dataset_hash:str|None=None
    positive_probability:float|None=None;expected_delta_auc:float|None=None;expected_delta_ks:float|None=None;expected_delta_lift10:float|None=None
    uncertainty:str="HIGH";out_of_distribution:bool=False;meta_feature_hash:str|None=None;context_hash:str
    execution_selected_by_phase5:bool=False;selection_probability:float=0.0;execution_reason:str="";status:Literal["PREDICTED","NOT_SELECTED","SELECTED_BY_PHASE5","EXPERIMENT_RUNNING","ACTUAL_AVAILABLE","EVALUATED","INVALID","OOD"]="PREDICTED"
    final_selection_policy:str="PHASE5";shadow_only:bool=True;disagreement:str="LOW";llm_suggestion:str|None=None;backend_final_candidate_id:str|None=None
    actual_decision:str|None=None;actual_delta_auc:float|None=None;actual_delta_ks:float|None=None;actual_delta_lift10:float|None=None;actual_stability:str|None=None;actual_credit:dict[str,Any]=Field(default_factory=dict);actual_hypothesis_credit:dict[str,Any]=Field(default_factory=dict);experiment_id:str|None=None;state_after:str|None=None
    runtime_seconds:float=0.0;feature_count:int=0;compute_cost_estimate:float=0.0;memory_source:Literal["REAL","SYNTHETIC","TEST_FIXTURE"]="REAL"
class PredictionErrorRecord(BaseModel):
    error_id:str;shadow_id:str;surrogate_version:str|None=None;predicted:dict[str,Any];actual:dict[str,Any];absolute_error:dict[str,float];direction_error:bool;classification_error:bool;out_of_distribution:bool;feature_type:str="UNKNOWN";semantic_domain:str="UNKNOWN";model_type:str="UNKNOWN";diagnosis:str="UNKNOWN";action_type:str;created_at:str=Field(default_factory=utc_now)
