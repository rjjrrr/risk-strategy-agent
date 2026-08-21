from __future__ import annotations

import numpy as np
import pandas as pd


def population_stability_index(dev: pd.Series, oot: pd.Series, bins: int = 10) -> float:
    dev_valid, oot_valid = dev.dropna(), oot.dropna()
    if dev_valid.empty or oot_valid.empty:
        return 0.0
    dev_numeric = pd.to_numeric(dev_valid, errors="coerce")
    oot_numeric = pd.to_numeric(oot_valid, errors="coerce")
    numeric = dev_numeric.notna().mean() >= 0.8 and oot_numeric.notna().mean() >= 0.8
    if numeric and dev_numeric.nunique() > bins:
        edges = np.unique(dev_numeric.quantile(np.linspace(0, 1, bins + 1)).to_numpy())
        if len(edges) >= 2:
            edges[0], edges[-1] = -np.inf, np.inf
            dev_bins = pd.cut(dev_numeric, edges, include_lowest=True).astype(str)
            oot_bins = pd.cut(oot_numeric, edges, include_lowest=True).astype(str)
        else:
            dev_bins, oot_bins = dev_valid.astype(str), oot_valid.astype(str)
    else:
        dev_bins, oot_bins = dev_valid.astype(str), oot_valid.astype(str)
    categories = set(dev_bins.unique()) | set(oot_bins.unique())
    value = 0.0
    for category in categories:
        p = max(float((dev_bins == category).mean()), 1e-6)
        q = max(float((oot_bins == category).mean()), 1e-6)
        value += (p - q) * np.log(p / q)
    return float(value)


def psi_label(value: float, stable: float = 0.1, drift: float = 0.25) -> str:
    return "STABLE" if value < stable else "WATCH" if value < drift else "DRIFT"
