import json, time, uuid, pickle
from pathlib import Path
import pandas as pd
import numpy as np
from .. import config
from ..core.data_loader import load_data
from ..core.governance import govern
from ..core.numeric_scanner import scan_numeric
from ..core.category_scanner import scan_categories
from ..core.rule_deduplicator import deduplicate
from ..core.reporter import write_outputs
from core.analysis_state import STAGES, new_state, mark, stale_downstream, SUCCESS, RUNNING, FAILED, STALE, now
from core.stability import bootstrap
from core.rule_deduplicator import deduplicate

DATASETS={}; STATUS={}
DEPENDENCIES={"data_health":(),"governance":("data_health",),"variable_scan":("governance",),"candidate_rules":("variable_scan",),"stability":("candidate_rules",),"rule_groups":("candidate_rules",),"grading":("stability","rule_groups"),"report":("grading",)}
def _paths(dataset_id):
    d=config.UPLOAD_DIR/dataset_id; d.mkdir(parents=True,exist_ok=True); return d
def register_upload(filename, content):
    did=uuid.uuid4().hex[:12]; ext=Path(filename).suffix.lower()
    if ext not in config.ALLOWED_EXTENSIONS: raise ValueError("仅支持 csv/xlsx/xls")
    path=_paths(did)/("data"+ext); path.write_bytes(content); df=load_data(str(path)); df.insert(0,"__row_id__",np.arange(len(df),dtype=np.int64)); DATASETS[did]={"path":path,"df":df,"governance":None,"rules":[],"target":"target7","segment_field":"is_old","state":new_state(did,filename, len(df), len(df.columns))}; STATUS[did]={"status":"UPLOADED"}
    _save_state(DATASETS[did])
    return did, df
def get_dataset(dataset_id):
    if dataset_id not in DATASETS: raise KeyError("dataset不存在")
    return DATASETS[dataset_id]
def governance(dataset_id, target="target7", segment_field="is_old"):
    ds=get_dataset(dataset_id); _, meta=govern(ds["df"],target,segment_field); meta=meta[meta.field!="__row_id__"].copy(); p=_paths(dataset_id)/"governance_override.json"
    if p.exists():
        overrides=json.loads(p.read_text(encoding="utf-8"))
        for field, val in overrides.items():
            hit=meta.field==field
            if hit.any(): meta.loc[hit,"decision"]=val["manual_decision"]
    ds["governance"]=meta; return meta
def patch_governance(dataset_id, field, decision):
    ds=get_dataset(dataset_id); meta=ds["governance"] if ds["governance"] is not None else governance(dataset_id)
    hit=meta.field==field
    if not hit.any(): raise KeyError("field不存在")
    p=_paths(dataset_id)/"governance_override.json"; old=json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    old[field]={"field":field,"original_decision":str(meta.loc[hit,"original_decision"].iloc[0]),"manual_decision":decision,"timestamp":time.time()}; p.write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding="utf-8"); meta.loc[hit,"decision"]=decision; stale_downstream(ds["state"],"governance"); _save_state(ds); return meta.loc[hit].iloc[0].to_dict()
def run_analysis(dataset_id, target="target7", segment_field="is_old"):
    run_all(dataset_id, target=target, segment_field=segment_field, force=True)
    return get_dataset(dataset_id)["rules"]

def _internal(ds):
    d=_paths(ds["state"]["dataset_id"])/"internal"; d.mkdir(parents=True,exist_ok=True); return d
def _save_state(ds):
    p=_paths(ds["state"]["dataset_id"])/"analysis_state.json"; p.write_text(json.dumps(ds["state"],ensure_ascii=False,indent=2),encoding="utf-8")
def get_state(dataset_id): return get_dataset(dataset_id)["state"]
def configure(dataset_id,target="target7",segment_field="is_old",application_time_field=None,same_group_jaccard=0.90,similar_jaccard=0.80):
    ds=get_dataset(dataset_id); st=ds["state"]; application_time_field=application_time_field or st["config"].get("application_time_field"); threshold_changed=(st["config"].get("same_group_jaccard")!=same_group_jaccard or st["config"].get("similar_jaccard")!=similar_jaccard); changed=(st["config"].get("target")!=target or st["config"].get("segment_field")!=segment_field or st["config"].get("application_time_field")!=application_time_field or threshold_changed); ds["target"]=target; ds["segment_field"]=segment_field; ds["application_time_field"]=application_time_field; st["config"].update(target=target,segment_field=segment_field,application_time_field=application_time_field,same_group_jaccard=same_group_jaccard,similar_jaccard=similar_jaccard); 
    if threshold_changed:
        stale_downstream(st,"rule_groups")
    elif changed:
        stale_downstream(st,"data_health")
    _save_state(ds); return st
def _prepared(ds):
    target,seg=ds.get("target","target7"),ds.get("segment_field","is_old"); df=ds["df"].copy()
    if target not in df or seg not in df: raise ValueError("target 或 segment 字段不存在")
    df=df.rename(columns={target:"__target__",seg:"__segment_raw__"}); df["__target__"]=pd.to_numeric(df.__target__,errors="coerce"); df=df[df.__target__.isin([0,1])].copy(); df["__segment__"]=df.__segment_raw__.map(lambda x:"NEW" if x==0 else "OLD" if x==2 else str(x)); return df
def _run_stage(ds,stage,fn):
    st=ds["state"]; started=now(); mark(st,stage,RUNNING); _save_state(ds)
    try:
        summary=fn(); finished=now(); mark(st,stage,SUCCESS,summary); st["stage_meta"][stage].update(started_at=started,finished_at=finished); _save_state(ds); return {"stage":stage,"status":SUCCESS,"started_at":started,"finished_at":finished,"summary":summary}
    except Exception as e:
        finished=now(); mark(st,stage,FAILED,error=str(e)); st["stage_meta"][stage].update(started_at=started,finished_at=finished); _save_state(ds); raise
def _require(ds,stage):
    missing=[x for x in DEPENDENCIES[stage] if ds["state"]["stage_status"].get(x)!=SUCCESS]
    if missing: raise ValueError(f"阶段 {stage} 依赖未完成: {', '.join(missing)}")
def run_data_health(dataset_id):
    ds=get_dataset(dataset_id)
    def work():
        df=ds["df"]; target=ds.get("target","target7"); seg=ds.get("segment_field","is_old"); summary={"rows":len(df),"columns":len(df.columns),"target_missing":int(df[target].isna().sum()) if target in df else None,"duplicate_rows":int(df.duplicated().sum()),"all_empty_fields":int(df.isna().all().sum()),"constant_fields":int((df.nunique(dropna=True)<=1).sum())}
        if seg in df: summary.update(NEW=int((df[seg]==0).sum()),OLD=int((df[seg]==2).sum()))
        ds["state"]["stages"]["data_health"]=summary; return summary
    return _run_stage(ds,"data_health",work)
def run_governance(dataset_id):
    ds=get_dataset(dataset_id)
    _require(ds,"governance")
    def work():
        _,meta=govern(ds["df"],ds.get("target","target7"),ds.get("segment_field","is_old")); meta=meta[meta.field!="__row_id__"].copy(); p=_paths(dataset_id)/"governance_override.json"
        if p.exists():
            for field,val in json.loads(p.read_text(encoding="utf-8")).items(): meta.loc[meta.field==field,"decision"]=val["manual_decision"]
        ds["governance"]=meta; ds["state"]["stages"]["governance"]={"rows":len(meta),"decision_counts":{k:int(v) for k,v in meta.decision.value_counts().items()},"pending_review":int(meta.decision.isin(["SUSPECT_LEAKAGE","REVIEW"]).sum())}; return ds["state"]["stages"]["governance"]
    return _run_stage(ds,"governance",work)
def run_variable_scan(dataset_id):
    ds=get_dataset(dataset_id)
    _require(ds,"variable_scan")
    def work():
        if ds["governance"] is None: raise ValueError("请先执行字段治理")
        df=_prepared(ds); rules=[]; meta=ds["governance"][ds["governance"].decision=="KEEP"]
        for seg in ["NEW","OLD"]:
            part=df[df.__segment__==seg].copy()
            if part.empty: continue
            rules += [dict(segment=seg,**r) for r in scan_numeric(part,meta,seg)]
            rules += [dict(segment=seg,**r) for r in scan_categories(part,meta,seg)]
            for r in rules:
                if r.get("segment")==seg and r.get("_mask") is not None:
                    global_mask=pd.Series(False,index=df.index); global_mask.loc[part.index]=r["_mask"]; r["_mask_global"]=global_mask.to_numpy()
        meta_by_field={r.field:r for _,r in meta.iterrows()}; rejected=[]; guarded=[]
        for r in rules:
            field_meta=meta_by_field.get(r.get("field")); series=ds["df"].get(r.get("field"))
            if field_meta is not None and getattr(field_meta,"semantic_type","")=="DATETIME": rejected.append({"rule":r.get("rule"),"reason":"DATETIME_HARD_BLOCK"}); continue
            if series is not None and pd.api.types.is_numeric_dtype(series) and series.nunique(dropna=True)>10 and "==" in str(r.get("rule")):
                rejected.append({"rule":r.get("rule"),"reason":"NUMERIC_HIGH_CARD_EQUALITY_FORBIDDEN"}); continue
            guarded.append(r)
        rules=guarded
        counters={"NEW":0,"OLD":0}; by_segment={"NEW":{},"OLD":{}}
        for r in rules:
            seg=r.get("segment","UNK"); counters[seg]=counters.get(seg,0)+1; r.setdefault("rule_id",f"{seg}_R{counters[seg]:06d}"); by_segment.setdefault(seg,{})[r["rule_id"]]=r.get("_mask_global")
        internal=_internal(ds)
        pickle.dump({r["rule_id"]:r.get("_mask_global") for r in rules},open(internal/"rule_hit_masks.pkl","wb"))
        for seg,masks in by_segment.items():
            valid=[r for r in rules if r.get("segment")==seg]; matrix=np.vstack([np.asarray(r.get("_mask_global"),dtype=bool) for r in valid]) if valid else np.zeros((0,len(df)),dtype=bool)
            np.savez_compressed(internal/f"rule_hit_masks_{seg.lower()}.npz",rule_ids=np.array(list(masks.keys())),masks=matrix)
            (internal/f"rule_hit_mask_meta_{seg.lower()}.json").write_text(json.dumps({"segment":seg,"row_ids":df["__row_id__"].astype(int).tolist(),"rule_ids":list(masks.keys())}),encoding="utf-8")
        ds["rules"]=rules; ds["state"]["stages"]["variable_scan"]={"fields_scanned":int(len(meta)),"raw_rules":len(rules),"hit_masks":len(rules),"rejected_rules":len(rejected),"rejected_reasons":rejected[:100]}; return ds["state"]["stages"]["variable_scan"]
    return _run_stage(ds,"variable_scan",work)
def run_candidate_rules(dataset_id):
    ds=get_dataset(dataset_id)
    _require(ds,"candidate_rules")
    def work():
        ds["state"]["stages"]["candidate_rules"]={"count":len(ds["rules"]),"representative_count":len([r for r in ds["rules"] if r.get("is_representative",True)])}; return ds["state"]["stages"]["candidate_rules"]
    return _run_stage(ds,"candidate_rules",work)
def run_stability(dataset_id):
    ds=get_dataset(dataset_id)
    _require(ds,"stability")
    def work():
        df=_prepared(ds)
        for r in ds["rules"]:
            mask=pd.Series(r.get("_mask_global",np.zeros(len(df),dtype=bool)),index=df.index); bootstrap(r,mask,df)
        ds["state"]["stages"]["stability"]={"count":len(ds["rules"]),"stable":int(sum(r.get("bootstrap_positive_ratio",0)>=.9 for r in ds["rules"]))}; return ds["state"]["stages"]["stability"]
    import numpy as np
    return _run_stage(ds,"stability",work)
def _build_group_artifacts(ds):
    df=_prepared(ds); internal=_internal(ds); rules=ds["rules"]; groups={}
    if not rules:
        for seg in ("NEW","OLD"):
            np.savez_compressed(internal/f"jaccard_{seg.lower()}.npz",matrix=np.zeros((0,0),dtype=float))
            (internal/f"jaccard_{seg.lower()}_rules.json").write_text("[]",encoding="utf-8")
        summary={"raw_rules":0,"rule_count":0,"group_count":0,"representatives":0,"compression_ratio":0,"summaries":[]}
        (internal/"rule_groups.json").write_text("[]",encoding="utf-8"); (internal/"cluster_summary.json").write_text(json.dumps(summary),encoding="utf-8"); return summary
    for r in rules: groups.setdefault((r.get("segment"),r.get("rule_group_id")),[]).append(r)
    summaries=[]
    for (seg,gid),rs in groups.items():
        rep=min(rs,key=lambda r:(0 if r.get("grade")=="A" else 1 if r.get("grade")=="B" else 2 if r.get("grade")=="REVIEW" else 3, {"STRONG":0,"WEAK":1,"NOT_AVAILABLE":2,"FAILED":3}.get(r.get("oot_status"),2), -float(r.get("lift") or 0), -float(r.get("coverage") or 0), -int(r.get("hit_count") or 0), -float(r.get("bootstrap_positive_ratio") or 0)))
        masks=[np.asarray(r.get("_mask_global",np.zeros(len(df),bool)),bool) for r in rs]; union=np.logical_or.reduce(masks) if masks else np.array([],bool); core=np.logical_and.reduce(masks) if masks else np.array([],bool)
        pairs=[float(np.logical_and(masks[i],masks[j]).sum()/np.logical_or(masks[i],masks[j]).sum()) for i in range(len(masks)) for j in range(i) if np.logical_or(masks[i],masks[j]).sum()]
        avg=float(np.mean(pairs)) if pairs else 1.0; min_j=float(min(pairs)) if pairs else 1.0; max_j=float(max(pairs)) if pairs else 1.0
        summaries.append({"rule_group_id":gid,"segment":seg,"representative_rule_id":rep.get("rule_id"),"representative_field":rep.get("field"),"representative_rule":rep.get("rule"),"rule_count":len(rs),"avg_jaccard":avg,"average_jaccard":avg,"min_jaccard":min_j,"max_jaccard":max_j,"representative_hit_count":rep.get("hit_count"),"representative_bad_rate":rep.get("bad_rate"),"representative_lift":rep.get("lift"),"representative_coverage":rep.get("coverage"),"oot_status":rep.get("oot_status","NOT_AVAILABLE"),"union_hit_count":int(union.sum()),"core_hit_count":int(core.sum()),"core_ratio":float(core.sum()/union.sum()) if union.sum() else 0.0,"cluster_quality":"TIGHT" if avg>=.90 else "MODERATE" if avg>=.80 else "LOOSE","quality":"TIGHT" if avg>=.90 else "MODERATE" if avg>=.80 else "LOOSE","warning":"LOOSE_CLUSTER_WARNING" if min_j<.75 else None})
    for seg in ["NEW","OLD"]:
        rs=[r for r in rules if r.get("segment")==seg]; masks=[np.asarray(r.get("_mask_global",np.zeros(len(df),bool)),bool) for r in rs]; matrix=np.eye(len(rs),dtype=float)
        for i in range(len(rs)):
            for j in range(i+1,len(rs)):
                u=np.logical_or(masks[i],masks[j]).sum(); matrix[i,j]=matrix[j,i]=float(np.logical_and(masks[i],masks[j]).sum()/u) if u else 0.0
        np.savez_compressed(internal/f"jaccard_{seg.lower()}.npz",matrix=matrix); (internal/f"jaccard_{seg.lower()}_rules.json").write_text(json.dumps([r.get("rule_id",f"{seg}_R{i+1:06d}") for i,r in enumerate(rs)]),encoding="utf-8")
    reps=sum(r.get("is_representative",True) for r in rules); summary={"raw_rules":len(rules),"rule_count":len(rules),"group_count":len(summaries),"representatives":reps,"compression_ratio":1-reps/len(rules) if rules else 0,"summaries":summaries}
    (internal/"rule_groups.json").write_text(json.dumps([{k:v for k,v in r.items() if not k.startswith("_")} for r in rules],ensure_ascii=False),encoding="utf-8"); (internal/"cluster_summary.json").write_text(json.dumps(summary,ensure_ascii=False),encoding="utf-8"); return summary
def run_rule_groups(dataset_id):
    ds=get_dataset(dataset_id)
    _require(ds,"rule_groups")
    def work():
        expected=len(ds["rules"]); loaded=sum(1 for r in ds["rules"] if r.get("_mask_global") is not None)
        print(f"[Rule Group Stage]\nCandidate rules = {expected}\nHit masks loaded = {loaded}")
        if expected!=loaded: raise ValueError(f"Candidate rule hit masks are incomplete. Expected {expected} masks, loaded {loaded}. Please rerun Candidate Rule stage.")
        apply_oot(ds); ds["rules"]=deduplicate(ds["rules"],_prepared(ds),ds["state"]["config"].get("same_group_jaccard",.90),ds["state"]["config"].get("similar_jaccard",.80)); s=_build_group_artifacts(ds)
        for seg in ("NEW","OLD"):
            m=np.load(_internal(ds)/f"jaccard_{seg.lower()}.npz")["matrix"]; ids=json.loads((_internal(ds)/f"jaccard_{seg.lower()}_rules.json").read_text(encoding="utf-8")); strong=int(((m>=.90)&(~np.eye(len(m),dtype=bool)).astype(bool)).sum()/2) if len(m) else 0; similar=int(((m>=.80)&(~np.eye(len(m),dtype=bool)).astype(bool)).sum()/2) if len(m) else 0; groups_seg=sum(x.get("segment")==seg for x in s["summaries"]); print(f"{seg} raw rules = {sum(r.get('segment')==seg for r in ds['rules'])}\n{seg} hit masks loaded = {len(ids)}\n{seg} jaccard matrix shape = {m.shape[0]} x {m.shape[1]}\n{seg} strong edges >= 0.90 = {strong}\n{seg} similar edges >= 0.80 = {similar}\n{seg} rule groups = {groups_seg}")
        if len(ds["rules"]) and (not all(r.get("rule_group_id") for r in ds["rules"]) or s["group_count"]<=0): raise ValueError("Rule Group validation failed: matrix or groups are incomplete.")
        ds["state"]["stages"]["rule_groups"]=s; return s
    return _run_stage(ds,"rule_groups",work)
def run_grading(dataset_id):
    ds=get_dataset(dataset_id)
    _require(ds,"grading")
    def work():
        apply_oot(ds); counts={s:{g:int(sum(r.get("segment")==s and r.get("grade")==g for r in ds["rules"])) for g in ["A","B","REVIEW","C"]} for s in ["NEW","OLD"]}; ds["state"]["stages"]["grading"].update(counts=counts); 
        if ds["state"]["stage_status"].get("rule_groups")==SUCCESS: ds["state"]["stages"]["rule_groups"]=_build_group_artifacts(ds)
        return ds["state"]["stages"]["grading"]
    return _run_stage(ds,"grading",work)
def run_report(dataset_id):
    ds=get_dataset(dataset_id)
    _require(ds,"report")
    def work():
        df=_prepared(ds); out=config.OUTPUT_DIR/dataset_id; write_outputs(ds["governance"].assign(segment="ALL"),ds["rules"],df,str(out)); ds["state"]["stages"]["report"]={"output_dir":str(out),"files":["variable_governance.csv","candidate_rules.csv","rule_report.md"]}; return ds["state"]["stages"]["report"]
    return _run_stage(ds,"report",work)
def _detect_time(ds):
    chosen=ds.get("application_time_field")
    if chosen and chosen in ds["df"]: return chosen
    for c in ds["df"].columns:
        name=str(c).lower()
        if any(x in name for x in ("apply_time","application_date","create_time","register_time")):
            parsed=pd.to_datetime(ds["df"][c],errors="coerce")
            if parsed.notna().mean()>=.7: return c
    return None
def apply_oot(ds):
    field=_detect_time(ds); rules=ds["rules"]
    if not field:
        for r in rules: r.update(oot_status="NOT_AVAILABLE",oot_warning="NO_OOT_WARNING")
        ds["state"]["stages"]["grading"]["oot_available"]=False; return
    df=_prepared(ds); times=pd.to_datetime(ds["df"][field],errors="coerce"); available=times.notna()
    ds["state"]["config"]["application_time_field"]=field; ds["state"]["stages"]["grading"]["oot_available"]=True
    for seg in ["NEW","OLD"]:
        idx=df.index[(df.__segment__==seg)&available.loc[df.index]]; ordered=idx[np.argsort(times.loc[idx].to_numpy())]; cut=int(len(ordered)*.7); dev=set(ordered[:cut]); oot=set(ordered[cut:])
        for r in rules:
            if r.get("segment")!=seg: continue
            hit=set(df.index[np.asarray(r.get("_mask_global",np.zeros(len(df),bool)),bool)])
            def metrics(pool):
                n=len(hit&pool); bad=int(df.loc[list(hit&pool),"__target__"].sum()) if n else 0; total=len(pool); br=bad/n if n else 0; base=float(df.loc[list(pool),"__target__"].mean()) if total else 0; return n,n/total if total else 0,br,br/base if base else None
            dn,dc,db,dl=metrics(dev); on,oc,ob,ol=metrics(oot); r.update(dev_hit=dn,dev_coverage=dc,dev_bad_rate=db,dev_lift=dl,oot_hit=on,oot_coverage=oc,oot_bad_rate=ob,oot_lift=ol,direction_stable=bool(dl and ol and dl>1 and ol>1),oot_status="STRONG" if ol is not None and ol>=1.2 and dl>1 and ol>1 else "WEAK" if ol is not None and ol>=1 else "FAILED" if ol is not None else "NOT_AVAILABLE")
            if r.get("grade")=="A" and r.get("oot_status") not in ("STRONG","NOT_AVAILABLE"): r["grade"]="B"
    return
def run_all(dataset_id,target="target7",segment_field="is_old",application_time_field=None,force=False):
    ds=get_dataset(dataset_id); cfg=ds["state"].get("config",{}); configure(dataset_id,target,segment_field,application_time_field,cfg.get("same_group_jaccard",.90),cfg.get("similar_jaccard",.80))
    sequence=[("data_health",run_data_health),("governance",run_governance),("variable_scan",run_variable_scan),("candidate_rules",run_candidate_rules),("stability",run_stability),("rule_groups",run_rule_groups),("grading",run_grading),("report",run_report)]
    results=[]
    for name,fn in sequence:
        if not force and ds["state"]["stage_status"].get(name)==SUCCESS: results.append({"stage":name,"status":SUCCESS,"summary":ds["state"]["stage_meta"].get(name,{}).get("summary",{})}); continue
        results.append(fn(dataset_id))
    STATUS[dataset_id]={"status":"SUCCESS"}; return {"dataset_id":dataset_id,"status":"SUCCESS","stages":results,"state":ds["state"]}
    if target not in df or segment_field not in df: raise ValueError("target 或 segment 字段不存在")
    df=df.rename(columns={target:"__target__",segment_field:"__segment_raw__"}); df["__target__"]=pd.to_numeric(df.__target__,errors="coerce"); df=df[df.__target__.isin([0,1])].copy(); df["__segment__"]=df.__segment_raw__.map(lambda x:"NEW" if x==0 else "OLD" if x==2 else str(x))
    meta=governance(dataset_id,target,segment_field); rules=[]
    for seg in ["NEW","OLD"]:
        part=df[df.__segment__==seg].copy()
        if part.empty: continue
        segmeta=meta[meta.decision=="KEEP"]
        rules += [dict(segment=seg,**r) for r in scan_numeric(part,segmeta,seg)]
        rules += [dict(segment=seg,**r) for r in scan_categories(part,segmeta,seg)]
    rules=deduplicate(rules,df); ds["rules"]=rules; STATUS[dataset_id]={"status":"SUCCESS"}
    out=config.OUTPUT_DIR/dataset_id; write_outputs(meta.assign(segment="ALL"),rules,df,str(out)); return rules
