"""Serializable, agent-ready state contract for staged analysis."""
from datetime import datetime, timezone
from typing import Any, Dict, TypedDict

STAGES=("data_health","governance","variable_scan","candidate_rules","stability","rule_groups","grading","report")
NOT_STARTED="NOT_STARTED"; RUNNING="RUNNING"; SUCCESS="SUCCESS"; FAILED="FAILED"; STALE="STALE"

def now(): return datetime.now(timezone.utc).isoformat()
class AnalysisState(TypedDict, total=False):
    dataset_id: str
    dataset: Dict[str, Any]
    config: Dict[str, Any]
    stages: Dict[str, Dict[str, Any]]
    stage_status: Dict[str, str]
    stage_meta: Dict[str, Dict[str, Any]]
    current_stage: str
    updated_at: str
def new_state(dataset_id, filename="", rows=0, columns=0):
    return {"dataset_id":dataset_id,"dataset":{"filename":filename,"rows":rows,"columns":columns},"config":{"target":"target7","bad_label":1,"good_label":0,"segment_field":"is_old","segment_mapping":{"0":"NEW","2":"OLD"},"application_time_field":None,"same_group_jaccard":0.90,"similar_jaccard":0.80},"stages":{s:{} for s in STAGES},"stage_status":{s:NOT_STARTED for s in STAGES},"stage_meta":{s:{} for s in STAGES},"current_stage":None,"updated_at":now()}

def mark(state, stage, status, summary=None, error=None):
    state["stage_status"][stage]=status; state["current_stage"]=None if status in (SUCCESS,FAILED) else stage; state["updated_at"]=now()
    state["stage_meta"][stage]={"stage":stage,"status":status,"updated_at":state["updated_at"],"summary":summary or {},"error":error}
    return state

def stale_downstream(state, stage):
    i=STAGES.index(stage)
    for s in STAGES[i+1:]:
        if state["stage_status"].get(s)==SUCCESS: state["stage_status"][s]=STALE
    state["updated_at"]=now(); return state
