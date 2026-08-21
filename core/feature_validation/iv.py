from __future__ import annotations

import numpy as np
import pandas as pd


def bin_feature(series: pd.Series, reference: pd.Series | None = None, bins: int = 10) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    source = pd.to_numeric(reference, errors="coerce") if reference is not None else numeric
    if numeric.notna().mean() >= 0.8 and source.nunique(dropna=True) > bins:
        edges = np.unique(source.dropna().quantile(np.linspace(0, 1, bins + 1)).to_numpy())
        if len(edges) >= 2:
            edges[0], edges[-1] = -np.inf, np.inf
            return pd.cut(numeric, edges, include_lowest=True).astype(str)
    return series.astype(object).where(series.notna(), "__MISSING__").astype(str)


def information_value(series: pd.Series, target: pd.Series, bins: int = 10) -> float:
    # Variable-specific denominator: rows missing this feature are excluded first.
    valid = series.notna() & target.isin([0, 1])
    x, y = bin_feature(series[valid], bins=bins), target[valid].astype(int)
    if y.empty or y.nunique() < 2:
        return 0.0
    bad_total, good_total = max(int(y.sum()), 1), max(int((1 - y).sum()), 1)
    value = 0.0
    for category in x.unique():
        mask = x == category
        bad, good = int(y[mask].sum()), int((1 - y[mask]).sum())
        bad_share = max(bad / bad_total, 1e-6)
        good_share = max(good / good_total, 1e-6)
        value += (bad_share - good_share) * np.log(bad_share / good_share)
    return float(value)
