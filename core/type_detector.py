import numpy as np
import pandas as pd
from . import config

def detect_type(s, decision="KEEP"):
    if decision != "KEEP": return "excluded"
    x = s.dropna(); n = len(x); u = x.nunique()
    if n == 0: return "excluded"
    if pd.api.types.is_datetime64_any_dtype(s): return "datetime"
    numeric = pd.api.types.is_numeric_dtype(s)
    if numeric:
        vals = pd.to_numeric(x, errors="coerce").dropna()
        integer_ratio = np.mean(np.isclose(vals % 1, 0)) if len(vals) else 0
        if u <= config.LOW_CARDINALITY_MAX and integer_ratio > .95 and (vals >= 0).mean() >= .8: return "numeric_count"
        return "numeric_continuous"
    if u <= config.LOW_CARDINALITY_MAX: return "categorical_low_cardinality"
    if u <= config.MEDIUM_CARDINALITY_MAX: return "categorical_medium_cardinality"
    return "categorical_high_cardinality"
