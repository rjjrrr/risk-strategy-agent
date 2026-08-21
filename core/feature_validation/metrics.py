from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def distribution_summary(series: pd.Series, target: pd.Series) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    valid = series.notna() & target.isin([0, 1])
    x, y = series[valid], target[valid].astype(int)
    numeric = pd.to_numeric(x, errors="coerce")
    warnings: list[str] = []
    if numeric.notna().mean() >= 0.8:
        finite = numeric.replace([np.inf, -np.inf], np.nan)
        q = finite.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
        summary = {
            "kind": "NUMERIC", "min": finite.min(), "p01": q.get(0.01), "p05": q.get(0.05),
            "p25": q.get(0.25), "p50": q.get(0.5), "p75": q.get(0.75), "p95": q.get(0.95),
            "p99": q.get(0.99), "max": finite.max(), "mean": finite.mean(), "std": finite.std(),
            "positive_inf": int(np.isposinf(numeric).sum()), "negative_inf": int(np.isneginf(numeric).sum()),
        }
        if summary["positive_inf"] or summary["negative_inf"]:
            warnings.append("INFINITE_VALUES")
        iqr = q.get(0.75, 0) - q.get(0.25, 0)
        if pd.notna(iqr) and iqr > 0 and ((finite < q.get(0.25) - 10 * iqr) | (finite > q.get(0.75) + 10 * iqr)).mean() > 0.01:
            warnings.append("EXTREME_OUTLIER")
        if numeric.nunique() > 1:
            top = numeric >= numeric.quantile(0.9)
            bottom = numeric <= numeric.quantile(0.1)
            groups = [("TOP_10", top), ("BOTTOM_10", bottom)]
        else:
            groups = [("CONSTANT", pd.Series(True, index=numeric.index))]
    else:
        counts = x.astype(str).value_counts(dropna=False)
        rates = pd.DataFrame({"x": x.astype(str), "y": y}).groupby("x")["y"].mean()
        summary = {
            "kind": "CATEGORICAL",
            "top_values": [{"value": str(k), "count": int(v), "rate": float(v / len(x))} for k, v in counts.head(20).items()],
            "rare_ratio": float(counts[counts < max(2, len(x) * 0.01)].sum() / len(x)) if len(x) else 0.0,
        }
        if x.nunique() > max(50, len(x) * 0.2):
            warnings.append("HIGH_CARDINALITY")
        groups = [(str(category), x.astype(str) == str(category)) for category in rates.sort_values(ascending=False).head(20).index]
    base = float(y.mean()) if len(y) else 0.0
    patterns = []
    for label, mask in groups:
        count = int(mask.sum())
        rate = float(y[mask].mean()) if count else None
        patterns.append({"group": label, "count": count, "coverage": count / len(x) if len(x) else 0.0, "bad_rate": rate, "lift": rate / base if rate is not None and base else None})
    best = max((p for p in patterns if p["lift"] is not None), key=lambda p: p["lift"], default={})
    return summary, {"base_bad_rate": base, "groups": patterns, "best_group": best, "max_lift": best.get("lift")}, warnings


def temporal_summary(series: pd.Series, target: pd.Series, times: pd.Series | None) -> tuple[list[dict], list[str]]:
    if times is None:
        return [], ["NO_TIME_FIELD"]
    parsed = pd.to_datetime(times, errors="coerce")
    valid = series.notna() & target.isin([0, 1]) & parsed.notna()
    if not valid.any():
        return [], ["NO_VALID_TIME_ROWS"]
    work = pd.DataFrame({"x": series[valid], "y": target[valid].astype(int), "period": parsed[valid].dt.to_period("M").astype(str)})
    numeric = pd.to_numeric(work["x"], errors="coerce")
    work["hit"] = numeric >= numeric.quantile(0.9) if numeric.notna().mean() >= 0.8 else work["x"].astype(str) == work.groupby("x")["y"].mean().idxmax()
    rows = []
    for period, group in work.groupby("period", sort=True):
        base = float(group["y"].mean())
        hit = group["hit"]
        rate = float(group.loc[hit, "y"].mean()) if hit.any() else None
        rows.append({"period": period, "rows": len(group), "coverage": float(hit.mean()), "bad_rate": rate, "lift": rate / base if rate is not None and base else None})
    warnings = []
    lifts = [row["lift"] for row in rows if row["lift"] is not None]
    if lifts and min(lifts) < 0.8 and max(lifts) > 1.2:
        warnings.append("SIGN_FLIP")
    if len(lifts) >= 2 and lifts[-1] < 0.6 * max(lifts[:-1]):
        warnings.append("LIFT_COLLAPSE")
    coverages = [row["coverage"] for row in rows]
    if len(coverages) >= 2 and coverages[-1] < 0.5 * max(coverages[:-1]):
        warnings.append("COVERAGE_COLLAPSE")
    return rows, warnings
