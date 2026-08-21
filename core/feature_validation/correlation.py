from __future__ import annotations

import pandas as pd


def correlations(series: pd.Series, target: pd.Series, existing: pd.DataFrame | None = None) -> dict:
    x = pd.to_numeric(series, errors="coerce")
    valid = x.notna() & target.isin([0, 1])
    pearson = float(x[valid].corr(target[valid].astype(float), method="pearson")) if x[valid].nunique() > 1 else 0.0
    spearman = float(x[valid].corr(target[valid].astype(float), method="spearman")) if x[valid].nunique() > 1 else 0.0
    maximum, maximum_field = 0.0, None
    if existing is not None and x.notna().any():
        for field in existing.columns:
            other = pd.to_numeric(existing[field], errors="coerce")
            corr = x.corr(other, method="spearman")
            if pd.notna(corr) and abs(float(corr)) > maximum:
                maximum, maximum_field = abs(float(corr)), str(field)
    return {"pearson_target": pearson, "spearman_target": spearman, "max_existing_correlation": maximum, "max_correlation_field": maximum_field}
