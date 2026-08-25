from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


TARGET_PROXY_AUC = 0.99
MIN_PROXY_ROWS = 50


def _directionless_auc(y: pd.Series, score: pd.Series) -> float | None:
    valid = y.notna() & score.notna()
    if int(valid.sum()) < MIN_PROXY_ROWS or y.loc[valid].nunique() < 2 or score.loc[valid].nunique() < 2:
        return None
    auc = float(roc_auc_score(y.loc[valid].astype(int), score.loc[valid].astype(float)))
    return max(auc, 1.0 - auc)


def _scores(dev: pd.Series, oot: pd.Series, y_dev: pd.Series) -> tuple[pd.Series, pd.Series, str]:
    dev_numeric = pd.to_numeric(dev, errors="coerce")
    oot_numeric = pd.to_numeric(oot, errors="coerce")
    if dev_numeric.notna().mean() >= 0.8 and oot_numeric.notna().mean() >= 0.8:
        return dev_numeric, oot_numeric, "NUMERIC"
    mapping = pd.DataFrame({"value": dev.astype("string"), "target": y_dev}).groupby("value", dropna=False)["target"].mean()
    fallback = float(y_dev.mean())
    return dev.astype("string").map(mapping).fillna(fallback), oot.astype("string").map(mapping).fillna(fallback), "CATEGORICAL"


def audit_target_proxies(
    frame: pd.DataFrame,
    target: str,
    dev_index: pd.Index,
    oot_index: pd.Index,
    candidates: Iterable[str],
    *,
    threshold: float = TARGET_PROXY_AUC,
) -> dict[str, Any]:
    """Detect raw fields that almost perfectly reproduce the target in both time periods."""
    y_dev = pd.to_numeric(frame.loc[dev_index, target], errors="coerce")
    y_oot = pd.to_numeric(frame.loc[oot_index, target], errors="coerce")
    findings: list[dict[str, Any]] = []
    for field in candidates:
        if field not in frame or frame[field].nunique(dropna=True) <= 1:
            continue
        dev_score, oot_score, value_type = _scores(frame.loc[dev_index, field], frame.loc[oot_index, field], y_dev)
        dev_auc = _directionless_auc(y_dev, dev_score)
        oot_auc = _directionless_auc(y_oot, oot_score)
        if dev_auc is not None and oot_auc is not None and dev_auc >= threshold and oot_auc >= threshold:
            findings.append({
                "field": field,
                "dev_auc": dev_auc,
                "oot_auc": oot_auc,
                "value_type": value_type,
                "reason": "NEAR_PERFECT_TARGET_PROXY_ACROSS_TIME_SPLIT",
            })
    return {
        "threshold": threshold,
        "excluded_fields": [row["field"] for row in findings],
        "findings": findings,
        "status": "BLOCKED_TARGET_PROXIES" if findings else "PASS",
    }


def remove_target_proxies(
    frame: pd.DataFrame,
    target: str,
    dev_index: pd.Index,
    oot_index: pd.Index,
    candidates: Iterable[str],
) -> tuple[list[str], dict[str, Any]]:
    fields = list(dict.fromkeys(str(field) for field in candidates))
    audit = audit_target_proxies(frame, target, dev_index, oot_index, fields)
    blocked = set(audit["excluded_fields"])
    return [field for field in fields if field not in blocked], audit
