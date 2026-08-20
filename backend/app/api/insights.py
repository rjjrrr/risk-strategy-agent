import io, json, zipfile
from typing import Optional
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from ..services.analysis_service import get_dataset, governance
from .analysis import _public_rules
from .. import config
router=APIRouter(prefix="/api/analysis",tags=["insights"])

def _clean(v):
    if hasattr(v,"item"): return v.item()
    return v

@router.get("/{dataset_id}/overview")
def overview(dataset_id:str):
    try: ds=get_dataset(dataset_id); df=ds["df"]; meta=ds["governance"] if ds["governance"] is not None else governance(dataset_id); rules=ds["rules"]
    except Exception as e: raise HTTPException(404,str(e))
    segments={}
    if "is_old" in df and "target7" in df:
        for name,value in [("NEW",0),("OLD",2)]:
            x=df[df.is_old==value]; segments[name]={"count":len(x),"bad_rate":_clean(x.target7.mean()) if len(x) else None}
    g=meta.decision.value_counts().to_dict(); semantic=meta.semantic_type.value_counts().to_dict()
    representative=[r for r in rules if r.get("is_representative",True)]; group_stage=ds["state"]["stages"].get("rule_groups",{}); grading=ds["state"]["stages"].get("grading",{})
    oot={s:{x:int(sum(r.get("segment")==s and r.get("is_representative",True) and r.get("oot_status")==x for r in rules)) for x in ["STRONG","WEAK","FAILED","NOT_AVAILABLE"]} for s in ["NEW","OLD"]}
    compression={s:{"raw":sum(r.get("segment")==s for r in rules),"representative":sum(r.get("segment")==s and r.get("is_representative",True) for r in rules)} for s in ["NEW","OLD"]}
    for s,v in compression.items(): v["groups"]=len({r.get("rule_group_id") for r in representative if r.get("segment")==s and r.get("rule_group_id")}); v["compression_ratio"]=1-v["representative"]/v["raw"] if v["raw"] else 0
    return {"dataset":{"filename":ds["path"].name,"rows":len(df),"columns":len(df.columns)},"segments":segments,"governance":{"counts":{k:int(v) for k,v in g.items()},"semantic_counts":{k:int(v) for k,v in semantic.items()},"valid_fields":int((meta.decision=="KEEP").sum()),"missing_top":meta.nlargest(15,"missing_rate")[["field","missing_rate"]].to_dict("records"),"unique_top":meta.nlargest(15,"unique_ratio")[["field","unique_ratio"]].to_dict("records")},"rules":{"total":len(rules),"representative":len(representative),"grades":{s:{g:int(sum(r.get("segment")==s and r.get("grade")==g for r in representative)) for g in ["A","B","REVIEW","C"]} for s in ["NEW","OLD"]},"oot":oot},"rule_groups":{"count":len(set(r.get("rule_group_id") for r in representative)),"compression":compression,"summary":group_stage.get("summaries",[])},"grading":grading}

@router.get("/{dataset_id}/variables/{field}/bins")
def bins(dataset_id:str,field:str,segment: str="NEW"):
    try: ds=get_dataset(dataset_id); df=ds["df"]; target=ds.get("target","target7"); segfield=ds.get("segment_field","is_old")
    except Exception as e: raise HTTPException(404,str(e))
    if field not in df or target not in df or segfield not in df: raise HTTPException(404,"字段不存在")
    x=df[df[segfield]==(0 if segment=="NEW" else 2)].copy(); y=pd.to_numeric(x[target],errors="coerce"); valid=y.isin([0,1]) & x[field].notna(); x=x.loc[valid]; y=y.loc[valid]; base=float(y.mean()) if len(y) else 0
    value=pd.to_numeric(x[field],errors="coerce")
    if value.notna().sum() >= 2 and value.nunique()>1:
        groups=pd.qcut(value, q=min(10,value.nunique()), duplicates="drop"); work=pd.DataFrame({"bin":groups.astype(str),"y":y.values},index=x.index)
    else:
        work=pd.DataFrame({"bin":x[field].astype(str),"y":y.values},index=x.index)
    out=[]
    for name,part in work.groupby("bin",sort=False):
        n=len(part); bad=int(part.y.sum()); br=bad/n if n else 0; out.append({"bin":name,"n":n,"bad":bad,"good":n-bad,"bad_rate":br,"lift":br/base if base else None,"coverage":n/len(x) if len(x) else 0})
    field_rules=[r for r in ds["rules"] if r.get("field")==field and r.get("segment")==segment]
    return {"field":field,"segment":segment,"base_bad_rate":base,"bins":out,"candidate_thresholds":[{"rule":r.get("rule"),"threshold":r.get("threshold_or_category"),"grade":r.get("grade")} for r in field_rules]}

@router.get("/{dataset_id}/rule-groups")
def rule_groups(dataset_id:str,segment:Optional[str]=None):
    try: rows=get_dataset(dataset_id)["rules"]
    except Exception as e: raise HTTPException(404,str(e))
    groups={}
    for r in rows:
        if segment and r.get("segment")!=segment: continue
        groups.setdefault(r.get("rule_group_id"),[]).append(r)
    items=[{"rule_group_id":gid,"representative":_public_rules([next((r for r in rs if r.get("is_representative",True)),rs[0])])[0],"related_rules":_public_rules([r for r in rs if not r.get("is_representative",True)]),"count":len(rs)} for gid,rs in groups.items()]
    summary=get_dataset(dataset_id)["state"]["stages"].get("rule_groups",{})
    return {"summary":summary,"groups":items}
@router.get("/{dataset_id}/rule-groups/matrix")
def rule_group_matrix(dataset_id:str,segment:str="NEW",threshold:float=0.90,limit:int=30):
    ds=get_dataset(dataset_id); internal=config.UPLOAD_DIR/dataset_id/"internal"; path=internal/f"jaccard_{segment.lower()}.npz"; ids_path=internal/f"jaccard_{segment.lower()}_rules.json"
    if not path.exists(): raise HTTPException(404,"请先运行规则聚类")
    matrix=np.load(path)["matrix"]; ids=json.loads(ids_path.read_text(encoding="utf-8")); rows=[r for r in ds["rules"] if r.get("segment")==segment]; rows=rows[:len(ids)]; order=sorted(range(len(rows)),key=lambda i:(not rows[i].get("is_representative",True),-float(rows[i].get("lift") or 0),-float(rows[i].get("coverage") or 0))); selected=order[:min(limit,len(rows))]; nodes=[]; edges=[]
    for i in selected:
        r=rows[i]; nodes.append({"id":ids[i],"name":ids[i],"field":r.get("field"),"rule":r.get("rule"),"short_rule":str(r.get("rule",""))[:80],"grade":r.get("grade"),"lift":r.get("lift"),"coverage":r.get("coverage"),"rule_group_id":r.get("rule_group_id"),"is_representative":r.get("is_representative",True),"oot_status":r.get("oot_status","NOT_AVAILABLE")})
        for j in selected:
            if j>i and matrix[i,j]>=threshold: edges.append({"source":ids[i],"target":ids[j],"jaccard":float(matrix[i,j])})
    warnings=[{"type":"GROUP_INCONSISTENCY","rule_a":e["source"],"rule_b":e["target"]} for e in edges if next((n for n in nodes if n["id"]==e["source"]),{}).get("rule_group_id")!=next((n for n in nodes if n["id"]==e["target"]),{}).get("rule_group_id")]
    return {"segment":segment,"threshold":threshold,"nodes":nodes,"edges":edges,"warnings":warnings,"matrix":matrix[np.ix_(selected,selected)].tolist(),"rule_ids":[ids[i] for i in selected]}
@router.get("/{dataset_id}/jaccard")
def jaccard(dataset_id:str,segment:str="NEW",top_n:int=30):
    result=rule_group_matrix(dataset_id,segment,0.80,top_n); pairs=[]
    for i,a in enumerate(result["rule_ids"]):
        for j,b in enumerate(result["rule_ids"]):
            if j>i: pairs.append({"rule_a":a,"rule_b":b,"jaccard":result["matrix"][i][j]})
    pairs=sorted(pairs,key=lambda x:x["jaccard"],reverse=True)[:20]
    return {"rules":result["rule_ids"],"matrix":result["matrix"],"top_pairs":pairs,"segment":segment}
@router.get("/{dataset_id}/rule-network")
def rule_network(dataset_id:str,segment:str="NEW",threshold:float=0.90,limit:int=100):
    return rule_group_matrix(dataset_id,segment,threshold,limit)
@router.get("/{dataset_id}/stages/rule-groups/diagnostics")
def rule_group_diagnostics(dataset_id:str):
    ds=get_dataset(dataset_id); status=ds["state"]["stage_status"].get("rule_groups","NOT_STARTED"); rules=ds["rules"]; internal=config.UPLOAD_DIR/dataset_id/"internal"; result={"status":status,"raw_rules":len(rules),"hit_masks":sum(r.get("_mask_global") is not None for r in rules),"matrix_shape":None,"strong_edges":0,"similar_edges":0,"groups":0,"singleton_groups":0}
    for seg in ("NEW","OLD"):
        p=internal/f"jaccard_{seg.lower()}.npz"
        if p.exists():
            m=np.load(p)["matrix"]; result["matrix_shape"]=[int(m.shape[0]),int(m.shape[1])] if result["matrix_shape"] is None else result["matrix_shape"]; tri=np.triu(m,1); result["strong_edges"]+=int((tri>=.90).sum()); result["similar_edges"]+=int((tri>=.80).sum())
    summary=ds["state"]["stages"].get("rule_groups",{}); result["groups"]=int(summary.get("group_count",0)); result["singleton_groups"]=int(sum(x.get("rule_count")==1 for x in summary.get("summaries",[]))); return result
@router.get("/{dataset_id}/rule-groups/{group_id}")
def rule_group(dataset_id:str,group_id:str):
    result=rule_groups(dataset_id)["groups"]; hit=[x for x in result if x["rule_group_id"]==group_id]
    if not hit: raise HTTPException(404,"Rule Group 不存在")
    return hit[0]

def _export_path(dataset_id,name):
    path=config.OUTPUT_DIR/dataset_id/name
    if not path.exists(): raise HTTPException(404,"请先完成规则分析")
    return FileResponse(path,filename=name)
@router.get("/{dataset_id}/export/rules")
def export_rules(dataset_id:str): return _export_path(dataset_id,"candidate_rules.csv")
@router.get("/{dataset_id}/export/governance")
def export_governance(dataset_id:str): return _export_path(dataset_id,"variable_governance.csv")
@router.get("/{dataset_id}/export/report")
def export_report(dataset_id:str): return _export_path(dataset_id,"rule_report.md")
@router.get("/{dataset_id}/export/all")
def export_all(dataset_id:str):
    names=["candidate_rules.csv","variable_governance.csv","rule_report.md"]; buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
        for name in names:
            path=config.OUTPUT_DIR/dataset_id/name
            if not path.exists(): raise HTTPException(404,"请先完成规则分析")
            z.write(path,name)
    buf.seek(0); return StreamingResponse(buf,media_type="application/zip",headers={"Content-Disposition":f"attachment; filename={dataset_id}_risk_strategy_outputs.zip"})
