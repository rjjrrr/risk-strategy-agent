from __future__ import annotations

import numpy as np
import pandas as pd


def validate_values(values:pd.Series)->dict:
    series=pd.Series(values);valid=series.notna();stats={"unique":int(series.nunique(dropna=True))}
    numeric=pd.to_numeric(series,errors="coerce")
    if numeric.notna().any():stats.update({"min":float(numeric.min()),"max":float(numeric.max()),"mean":float(numeric.mean()),"std":float(numeric.std(ddof=0)),"infinite_count":int(np.isinf(numeric).sum())})
    return {"rows":len(series),"valid_count":int(valid.sum()),"missing_count":int((~valid).sum()),"missing_rate":float((~valid).mean()) if len(series) else 0.0,"statistics":stats,"sanity_status":"PASS" if valid.any() and stats.get("infinite_count",0)==0 else "REVIEW"}
