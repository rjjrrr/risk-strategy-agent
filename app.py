import argparse, os
import pandas as pd
from core.data_loader import load_data
from core.governance import govern
from core.numeric_scanner import scan_numeric
from core.category_scanner import scan_categories
from core.reporter import write_outputs
from core.utils import segment_name
from core.rule_deduplicator import deduplicate

def main():
    p=argparse.ArgumentParser(); p.add_argument("--input",required=True); p.add_argument("--target",default="target7"); p.add_argument("--segment-field",default="is_old"); p.add_argument("--output-dir",default="outputs"); a=p.parse_args()
    print("[1/7] Loading data"); df=load_data(a.input)
    if a.target not in df: raise ValueError(f"target不存在: {a.target}")
    if a.segment_field not in df: raise ValueError(f"segment字段不存在: {a.segment_field}")
    df=df.rename(columns={a.target:"__target__",a.segment_field:"__segment_raw__"}); df["__target__"]=pd.to_numeric(df.__target__,errors="coerce"); df=df[df.__target__.isin([0,1])].copy(); df["__segment__"]=df.__segment_raw__.map(segment_name)
    print("[2/7] Field governance"); clean, meta=govern(df.rename(columns={"__target__":a.target,"__segment_raw__":a.segment_field}),a.target,a.segment_field); clean=clean.rename(columns={a.target:"__target__",a.segment_field:"__segment_raw__"}); clean["__segment__"]=clean.__segment_raw__.map(segment_name)
    print("[3/7] Segmenting NEW / OLD"); all_rules=[]
    for seg in ["NEW","OLD"]:
        part=clean[clean.__segment__==seg].copy()
        if part.empty: continue
        segmeta=meta[~meta.field.isin([a.target,a.segment_field])]
        print("[4/7] Numeric variable scanning"); all_rules += [dict(segment=seg,**x) for x in scan_numeric(part,segmeta,seg)]
        print("[5/7] Category variable scanning"); all_rules += [dict(segment=seg,**x) for x in scan_categories(part,segmeta,seg)]
    all_rules=deduplicate(all_rules, clean)
    # Per-field compression: retain at most three passed candidates, favoring grade, stability and coverage.
    rank={"A":0,"B":1,"C":2}
    all_rules=sorted(all_rules,key=lambda x:(x["segment"],x["field"],rank.get(x.get("grade"),9),-x.get("bootstrap_positive_ratio",0),-x.get("coverage",0)))
    kept=[]; seen={}
    for x in all_rules:
        key=(x["segment"],x["field"]); seen[key]=seen.get(key,0)
        if seen[key] < 3: kept.append(x); seen[key]+=1
    print("[6/7] Rule validation");
    gov=pd.concat([meta.assign(segment=s) for s in ["NEW","OLD"]],ignore_index=True)
    rr=write_outputs(gov,kept,clean,a.output_dir)
    print("[7/7] Report generated");
    for seg in ["NEW","OLD"]:
        z=rr[rr.segment==seg] if len(rr) else pd.DataFrame(); print(f"{seg}:\nA rules = {(z.grade=='A').sum()}\nB rules = {(z.grade=='B').sum()}")
    print(f"Output:\n{os.path.join(a.output_dir,'variable_governance.csv')}\n{os.path.join(a.output_dir,'candidate_rules.csv')}\n{os.path.join(a.output_dir,'rule_report.md')}")
if __name__=="__main__": main()
