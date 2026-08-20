from typing import Optional
from fastapi import APIRouter, HTTPException
from ..schemas.dataset import RunRequest, RunAllRequest
from ..services.analysis_service import governance, run_analysis, get_dataset, configure, get_state, run_data_health, run_governance, run_variable_scan, run_candidate_rules, run_stability, run_rule_groups, run_grading, run_report, run_all, stale_downstream
router=APIRouter(prefix="/api/analysis",tags=["analysis"])

def _public_rules(rows):
    """Remove internal masks and convert NumPy scalar values for JSON responses."""
    result=[]
    for row in rows:
        clean={}
        for key, value in row.items():
            if key.startswith("_"): continue
            if hasattr(value, "item"):
                value=value.item()
            clean[key]=value
        result.append(clean)
    return result
@router.post("/{dataset_id}/governance")
def do_governance(dataset_id:str, request:RunRequest=RunRequest()):
    try: configure(dataset_id,request.target,request.segment_field,request.application_time_field,request.same_group_jaccard,request.similar_jaccard); result=run_governance(dataset_id); return {"result":result,"items":get_dataset(dataset_id)["governance"].where(get_dataset(dataset_id)["governance"].notna(),None).to_dict(orient="records")}
    except Exception as e: raise HTTPException(400,str(e))
@router.get("/{dataset_id}/governance")
def get_governance(dataset_id:str, decision:Optional[str]=None, search:Optional[str]=None, page:int=1, page_size:int=50):
    try: df=get_dataset(dataset_id)["governance"]
    except Exception as e: raise HTTPException(404,str(e))
    if df is None: df=governance(dataset_id)
    if decision: df=df[df.decision==decision]
    if search: df=df[df.field.astype(str).str.contains(search,case=False,na=False)]
    view=df.iloc[(page-1)*page_size:page*page_size]
    return {"total":len(df),"page":page,"page_size":page_size,"items":view.where(view.notna(),None).to_dict(orient="records")}
@router.post("/{dataset_id}/run")
def run(dataset_id:str, request:RunRequest):
    try: return {"status":"SUCCESS","rules":_public_rules(run_analysis(dataset_id,request.target,request.segment_field))}
    except Exception as e: raise HTTPException(400,str(e))

STAGE_FUNCS={"data-health":run_data_health,"governance":run_governance,"variable-scan":run_variable_scan,"candidate-rules":run_candidate_rules,"stability":run_stability,"rule-groups":run_rule_groups,"grading":run_grading,"report":run_report}
@router.post("/{dataset_id}/stages/{stage}/run")
def run_stage(dataset_id:str,stage:str,request:RunRequest=RunRequest()):
    if stage not in STAGE_FUNCS: raise HTTPException(404,"未知分析阶段")
    try:
        configure(dataset_id,request.target,request.segment_field,request.application_time_field,request.same_group_jaccard,request.similar_jaccard)
        ds=get_dataset(dataset_id)
        stage_key=stage.replace("-","_")
        stale_downstream(ds["state"], stage_key)
        sequence=["data-health","governance","variable-scan","candidate-rules","stability","rule-groups","grading","report"]
        start=sequence.index(stage)
        stages=sequence[start:] if request.mode=="FROM_HERE" else [stage]
        results=[STAGE_FUNCS[item](dataset_id) for item in stages]
        return {"mode":request.mode,"stage":stage,"results":results,"state":ds["state"]}
    except Exception as e: raise HTTPException(400,str(e))
@router.get("/{dataset_id}/state")
def state(dataset_id:str):
    try: return get_state(dataset_id)
    except Exception as e: raise HTTPException(404,str(e))
@router.post("/{dataset_id}/run-all")
def run_all_endpoint(dataset_id:str,request:RunAllRequest=RunAllRequest()):
    try:
        configure(dataset_id,request.target,request.segment_field,request.application_time_field,request.same_group_jaccard,request.similar_jaccard)
        return run_all(dataset_id,request.target,request.segment_field,request.application_time_field,request.force)
    except Exception as e: raise HTTPException(400,str(e))
