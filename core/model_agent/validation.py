from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _bins(series: pd.Series, reference: pd.Series | None = None, n: int = 10) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().mean() >= .8 and numeric.nunique(dropna=True) > n:
        source = pd.to_numeric(reference, errors="coerce") if reference is not None else numeric
        edges = np.unique(source.dropna().quantile(np.linspace(0, 1, n + 1)).to_numpy())
        if len(edges) >= 2:
            edges[0], edges[-1] = -np.inf, np.inf
            return pd.cut(numeric, edges, include_lowest=True).astype(str)
    return series.astype(object).where(series.notna(), "__MISSING__").astype(str)


def information_value(series: pd.Series, target: pd.Series) -> float:
    valid = series.notna() & target.isin([0, 1])
    x, y = _bins(series[valid]), target[valid].astype(int)
    total_bad, total_good = max(int(y.sum()), 1), max(int((1-y).sum()), 1)
    iv = 0.0
    for category in x.unique():
        mask = x == category; bad = int(y[mask].sum()); good = int((1-y[mask]).sum())
        bad_dist = max(bad / total_bad, 1e-6); good_dist = max(good / total_good, 1e-6)
        iv += (bad_dist - good_dist) * np.log(bad_dist / good_dist)
    return float(iv)


def population_stability(dev: pd.Series, oot: pd.Series) -> float:
    dev_bins, oot_bins = _bins(dev), _bins(oot, reference=dev)
    categories = set(dev_bins.unique()) | set(oot_bins.unique())
    psi = 0.0
    for category in categories:
        p = max(float((dev_bins == category).mean()), 1e-6)
        q = max(float((oot_bins == category).mean()), 1e-6)
        psi += (p-q) * np.log(p/q)
    return float(psi)


class CheapValidator:
    def validate(
        self, feature_name: str, series: pd.Series, target: pd.Series,
        dev_mask: pd.Series, oot_mask: pd.Series, existing_features: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        valid = series.notna() & target.isin([0, 1])
        x, y = series[valid], target[valid].astype(int)
        numeric = pd.to_numeric(x, errors="coerce")
        if numeric.notna().mean() >= .8:
            threshold = numeric.quantile(.9); hit = numeric >= threshold
            pearson = float(numeric.corr(y, method="pearson")) if numeric.nunique() > 1 else 0.0
            spearman = float(numeric.corr(y, method="spearman")) if numeric.nunique() > 1 else 0.0
        else:
            rates = pd.DataFrame({"x": x.astype(str), "y": y}).groupby("x").y.mean()
            risky = rates.idxmax() if len(rates) else None; hit = x.astype(str) == risky
            pearson = spearman = 0.0
        base = float(y.mean()) if len(y) else 0.0
        bad_rate = float(y[hit].mean()) if hit.any() else 0.0
        lift = bad_rate / base if base else None
        max_corr = 0.0
        if existing_features is not None and numeric.notna().mean() >= .8:
            for column in existing_features.columns:
                other = pd.to_numeric(existing_features.loc[x.index, column], errors="coerce")
                corr = numeric.corr(other, method="spearman")
                if corr == corr:
                    max_corr = max(max_corr, abs(float(corr)))
        psi = population_stability(series[dev_mask & series.notna()], series[oot_mask & series.notna()])
        iv = information_value(series, target)
        if series.notna().mean() < .2 or psi >= .25:
            status = "REJECTED"
        elif max_corr > .95:
            status = "REJECTED"
        elif lift is not None and lift >= 1.2 and psi < .1:
            status = "PROMISING"
        elif lift is not None and lift >= 1.05:
            status = "EXPLORATORY"
        else:
            status = "REVIEW"
        return {
            "feature": feature_name, "valid_rate": float(series.notna().mean()),
            "missing_rate": float(series.isna().mean()), "unique_count": int(series.nunique(dropna=True)),
            "bad_rate": bad_rate, "lift": lift, "iv": iv, "psi": psi,
            "temporal_stability": "STABLE" if psi < .1 else "WATCH" if psi < .25 else "DRIFTED",
            "pearson_target": pearson, "spearman_target": spearman,
            "max_existing_spearman": max_corr,
            "feature_novelty": "REDUNDANT_FEATURE" if max_corr > .95 else "NOVEL",
            "status": status,
        }


def select_feature_pools(features: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    lr, lgbm = [], []
    for row in features:
        validation = row.get("validation_result") or {}
        if validation.get("status") == "REJECTED":
            continue
        if row.get("semantic_domain") in {"TIME", "EXISTING_SCORE"} and row.get("feature_type") == "RAW":
            continue
        if validation.get("psi", 1) < .25 and validation.get("missing_rate", 1) < .8:
            lgbm.append(row["feature_name"])
        if validation.get("status") in {"PROMISING", "EXPLORATORY"} and validation.get("max_existing_spearman", 0) <= .95 and validation.get("psi", 1) < .1:
            lr.append(row["feature_name"])
    return lr, lgbm
