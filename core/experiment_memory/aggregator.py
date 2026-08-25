from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .schemas import AggregateCredit


def _number(row: dict, *keys: str) -> float:
    values = row.get("delta_metrics") or {}
    for key in keys:
        value = values.get(key)
        if value is not None:
            try: return float(value)
            except (TypeError, ValueError): pass
    return 0.0


def _confidence(count: int) -> str:
    return "HIGH" if count >= 20 else "MEDIUM" if count >= 5 else "LOW"


class CreditAggregator:
    def aggregate(self, rows: list[dict], dimension: str, *, by_model: bool = False, dataset_id: str | None = None) -> list[dict]:
        grouped: dict[tuple[str, str | None], list[dict]] = defaultdict(list)
        for row in rows:
            if row.get("source") == "SYNTHETIC" and dataset_id is not None:
                continue
            if dataset_id and row.get("dataset_id") != dataset_id:
                continue
            values = self._values(row, dimension)
            for value in values:
                grouped[(value, str(row.get("model_type")) if by_model else None)].append(row)
        result = []
        for (value, model), items in grouped.items():
            result.append(self._summarize(items, dimension, value, model, dataset_id))
        return sorted(result, key=lambda x: (-x["smoothed_positive_rate"], -x["sample_count"], x["value"], x.get("model_type") or ""))

    @staticmethod
    def _values(row: dict, dimension: str) -> Iterable[str]:
        mapping = {
            "FEATURE_TYPE": row.get("feature_types") or ["UNKNOWN"],
            "SEMANTIC_DOMAIN": row.get("semantic_domains") or ["UNKNOWN"],
            "ACTION_TYPE": [row.get("action_type") or "UNKNOWN"],
            "HYPOTHESIS_PATTERN": ["|".join([
                str((row.get("semantic_domains") or ["UNKNOWN"])[0]),
                str((row.get("feature_types") or ["UNKNOWN"])[0]),
                str((row.get("evidence_types") or ["UNKNOWN"])[0]),
            ])],
        }
        return [str(x) for x in mapping[dimension]]

    @staticmethod
    def _summarize(items: list[dict], dimension: str, value: str, model: str | None, dataset_id: str | None) -> dict:
        failed = [x for x in items if x.get("counterfactual_decision") == "FAILED"]
        valid = [x for x in items if x.get("counterfactual_decision") not in {"FAILED", "RUNNING", "REVIEW"}]
        count = len(valid)
        outcomes = [str(x.get("counterfactual_decision")) for x in valid]
        positive = outcomes.count("POSITIVE")
        stable = sum(x not in {"UNSTABLE"} for x in outcomes)
        row = AggregateCredit(
            dimension=dimension, value=value, model_type=model, dataset_id=dataset_id,
            experiment_count=len(items), sample_count=count, failed_count=len(failed), positive_count=positive,
            neutral_count=outcomes.count("NEUTRAL"), negative_count=outcomes.count("NEGATIVE"), unstable_count=outcomes.count("UNSTABLE"),
            positive_rate=positive / count if count else 0.0, smoothed_positive_rate=(positive + 1) / (count + 2),
            avg_delta_auc=sum(_number(x, "delta_oot_auc", "oot_auc") for x in valid) / count if count else 0.0,
            avg_delta_ks=sum(_number(x, "delta_oot_ks", "oot_ks") for x in valid) / count if count else 0.0,
            avg_delta_lift10=sum(_number(x, "delta_lift10", "delta_lift_10", "lift_10") for x in valid) / count if count else 0.0,
            stability_rate=stable / count if count else 0.0,
            rollback_rate=sum(str(x.get("action_outcome")) == "ROLLBACK" for x in items) / len(items) if items else 0.0,
            average_cost=sum(float(x.get("cost") or 0) for x in items) / len(items) if items else 0.0,
            confidence=_confidence(count),
        ).model_dump()
        row["credit_id"] = "|".join([dimension, value, model or "ALL", dataset_id or "GLOBAL"])
        row["credit_source"] = "REAL" if all(x.get("source", "REAL") == "REAL" for x in items) else "SYNTHETIC"
        if dimension == "ACTION_TYPE":
            row.update(success_rate=row["positive_rate"], average_gain=row["avg_delta_auc"], unstable_rate=(row["unstable_count"] / row["sample_count"] if row["sample_count"] else 0.0))
        return row

    def all_dimensions(self, rows: list[dict], *, dataset_id: str | None = None) -> dict[str, list[dict]]:
        return {
            "feature_types": self.aggregate(rows, "FEATURE_TYPE", dataset_id=dataset_id),
            "semantic_domains": self.aggregate(rows, "SEMANTIC_DOMAIN", dataset_id=dataset_id),
            "actions": self.aggregate(rows, "ACTION_TYPE", dataset_id=dataset_id),
            "model_specific": self.aggregate(rows, "FEATURE_TYPE", by_model=True, dataset_id=dataset_id),
            "hypothesis_patterns": self.aggregate(rows, "HYPOTHESIS_PATTERN", by_model=True, dataset_id=dataset_id),
        }
