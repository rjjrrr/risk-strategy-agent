import pandas as pd
from . import config
from .evaluator import evaluate
from .stability import bootstrap

def scan_categories(df, meta, segment):
    out=[]
    for _, r in meta[(meta.decision=="KEEP") & (meta.detected_type.str.startswith("categorical"))].iterrows():
        if getattr(r, "semantic_type", "") == "DATETIME":
            continue
        col=r.field; s=df[col].astype(object).where(df[col].notna(), "__MISSING__"); counts=s.value_counts(); rare=counts[(counts<config.MIN_CATEGORY_COUNT) | (counts/len(s)<config.MIN_CATEGORY_RATE)].index; s=s.where(~s.isin(rare), "__OTHER_RARE__")
        for cat in s.dropna().unique():
            mask=s==cat; row=evaluate(mask, df, col, f"{col} == {cat}", "category", cat, "类别坏率扫描", r.semantic_type)
            if row["status"] in ("PASS", "REVIEW"):
                row["_mask"] = mask.to_numpy(); out.append(bootstrap(row, mask, df))
    return out
