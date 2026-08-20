import numpy as np
import pandas as pd
from . import config
from .evaluator import evaluate
from .stability import bootstrap

def scan_numeric(df, meta, segment):
    out=[]
    for _, r in meta[(meta.decision=="KEEP") & (meta.detected_type.isin(["numeric_continuous","numeric_count"]))].iterrows():
        if getattr(r, "semantic_type", "") == "DATETIME":
            continue
        col=r.field; x=pd.to_numeric(df[col], errors="coerce"); valid=x.notna(); work=df.loc[valid]; xv=x[valid]
        if xv.nunique()<2: continue
        try: bins=pd.qcut(xv, q=min(config.NUMERIC_BINS, xv.nunique()), duplicates="drop")
        except Exception: continue
        stats=work.assign(__bin=bins).groupby("__bin", observed=True)["__target__"].agg(["count","sum","mean"])
        base=work.__target__.mean(); high=stats["mean"] >= base*config.MIN_LIFT
        # Only contiguous high-risk tails; isolated bins are intentionally ignored.
        candidates=[]
        for side in ("high","low"):
            b=high.to_numpy()[::-1] if side=="high" else high.to_numpy()
            k=0
            while k<len(b) and b[k]: k+=1
            if k>=1 and k < len(stats):
                edges=stats.index
                threshold=float(edges[len(edges)-k].left if side=="high" else edges[k-1].right)
                mask=(x>=threshold) if side=="high" else (x<=threshold)
                candidates.append((mask, f"{col} >= {threshold:g}" if side=="high" else f"{col} <= {threshold:g}", threshold))
        for mask, rule, threshold in candidates:
            row=evaluate(mask.loc[df.index], df, col, rule, "threshold", threshold, "连续风险尾部趋势", r.semantic_type)
            if row["status"] in ("PASS", "REVIEW"):
                row["_mask"] = mask.loc[df.index].to_numpy(); out.append(bootstrap(row, mask.loc[df.index], df))
    return out
