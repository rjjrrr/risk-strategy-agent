import re
import numpy as np
import pandas as pd
from . import config

def normalize_missing(s):
    def f(x):
        if pd.isna(x): return np.nan
        if isinstance(x, str) and x.strip() in config.SPECIAL_MISSING: return np.nan
        if isinstance(x, (int, float)) and x in config.SPECIAL_NUMERIC: return np.nan
        return x
    return s.map(f)

def safe_name(x): return re.sub(r"[^a-zA-Z0-9_]+", "_", str(x).lower())
def segment_name(v): return "NEW" if v == 0 else "OLD" if v == 2 else str(v)
def rate(n, d): return float(n / d) if d else np.nan
def empty(v): return v is None or (isinstance(v, str) and not v.strip())
