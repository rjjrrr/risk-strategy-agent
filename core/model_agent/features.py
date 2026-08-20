from __future__ import annotations

import uuid
from typing import Any

import numpy as np
import pandas as pd

from .config import FEATURE_TYPES
from .registry import FeatureRegistry


def _id() -> str:
    return f"F_{uuid.uuid4().hex[:10]}"


class FeatureGenerator:
    def __init__(self, registry: FeatureRegistry):
        self.registry = registry

    def generate(self, df: pd.DataFrame, hypothesis: dict[str, Any], experiment_id: str | None = None) -> list[dict[str, Any]]:
        output = []
        for proposal in hypothesis.get("candidate_features", []):
            feature_type = proposal["feature_type"]
            sources = proposal["source_fields"]
            if feature_type not in FEATURE_TYPES or any(field not in df for field in sources):
                continue
            if feature_type == "SHORT_LONG_RATIO":
                short, long = sources
                name = f"{short}_to_{long}_ratio"
                formula = f"{short} / max({long}, 1)"
                description = f"{short} divided by {long}; denominator is floored at 1 to avoid division by zero."
            elif feature_type == "RATIO":
                left, right = sources
                name = f"{left}_to_{right}_ratio"; formula = f"{left} / max({right}, 1)"
                description = f"{left} divided by {right}; denominator is floored at 1."
            elif feature_type == "DIFFERENCE":
                left, right = sources
                name = f"{left}_minus_{right}"; formula = f"{left} - {right}"
                description = f"Difference between {left} and {right}."
            elif feature_type == "RAW":
                name = sources[0]; formula = sources[0]; description = f"Original governed variable {sources[0]}."
            else:
                continue
            existing = self.registry.by_formula(formula, sources)
            if existing:
                output.append(existing); continue
            record = {
                "feature_id": _id(), "feature_name": name, "feature_version": "1.0",
                "feature_type": feature_type, "source_fields": sources, "source_feature_ids": [],
                "semantic_domain": hypothesis.get("risk_domain", "UNKNOWN"), "formula": formula,
                "calculation_description": description, "generation_reason": hypothesis["risk_mechanism"],
                "hypothesis_id": hypothesis["hypothesis_id"], "experiment_id": experiment_id,
                "expected_direction": hypothesis.get("expected_direction"), "status": "GENERATED",
                "validation_result": None, "lr_eligible": False, "lgbm_eligible": False, "approved": False,
            }
            self.registry.add(record); output.append(record)
        return output

    def generate_rule_group_features(self, rules: list[dict[str, Any]], row_count: int, experiment_id: str | None = None) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
        """Build representative/union/hit-count features from existing NEW rule groups."""
        groups: dict[str, list[dict[str, Any]]] = {}
        for rule in rules:
            if rule.get("segment") == "NEW" and rule.get("rule_group_id") and rule.get("_mask_global") is not None:
                groups.setdefault(str(rule["rule_group_id"]), []).append(rule)
        values: dict[str, pd.Series] = {}; records = []
        for group_id, members in groups.items():
            representative = next((x for x in members if x.get("is_representative")), members[0])
            ordered = [representative] + [x for x in members if x is not representative]
            masks = np.vstack([np.asarray(x["_mask_global"], dtype=bool)[:row_count] for x in ordered])
            variants = {
                "representative": masks[0].astype(int),
                "union": masks.any(axis=0).astype(int),
                "hit_count": masks.sum(axis=0).astype(int),
            }
            source_rule_ids = [str(x.get("rule_id")) for x in ordered]
            for aggregation, array in variants.items():
                name = f"rule_group_{group_id}_{aggregation}"
                formula = f"RULE_GROUP({group_id},{aggregation},{','.join(source_rule_ids)})"
                existing = self.registry.by_formula(formula, source_rule_ids)
                record = existing or self.registry.add({
                    "feature_id": _id(), "feature_name": name, "feature_version": "1.0",
                    "feature_type": "RULE_GROUP_FEATURE", "source_fields": source_rule_ids,
                    "source_feature_ids": [], "source_rule_ids": source_rule_ids,
                    "rule_group_id": group_id, "aggregation": aggregation,
                    "semantic_domain": "RULE_SIGNAL", "formula": formula,
                    "calculation_description": f"{aggregation} signal of NEW rule group {group_id}.",
                    "generation_reason": "Reuse evidence from stable and deduplicated deterministic rules.",
                    "hypothesis_id": None, "experiment_id": experiment_id,
                    "expected_direction": "HIGHER_RISK_WHEN_HIGH", "status": "GENERATED",
                    "validation_result": None, "lr_eligible": False, "lgbm_eligible": False, "approved": False,
                })
                values[name] = pd.Series(array); records.append(record)
        return pd.DataFrame(values), records

    @staticmethod
    def rebuild(df: pd.DataFrame, feature: dict[str, Any], rule_masks: dict[str, Any] | None = None) -> pd.Series:
        kind = feature["feature_type"]; sources = feature["source_fields"]
        if kind in {"RATIO", "SHORT_LONG_RATIO"}:
            left = pd.to_numeric(df[sources[0]], errors="coerce")
            right = pd.to_numeric(df[sources[1]], errors="coerce").clip(lower=1)
            return left / right
        if kind == "DIFFERENCE":
            return pd.to_numeric(df[sources[0]], errors="coerce") - pd.to_numeric(df[sources[1]], errors="coerce")
        if kind == "RAW":
            return df[sources[0]].copy()
        if kind == "RULE_GROUP_FEATURE":
            if rule_masks is None: raise ValueError("RULE_GROUP_FEATURE rebuild requires rule_masks")
            masks=np.vstack([np.asarray(rule_masks[rule_id],dtype=bool) for rule_id in feature["source_rule_ids"]])
            aggregation=feature["aggregation"]
            if aggregation=="representative": return pd.Series(masks[0].astype(int),index=df.index)
            if aggregation=="union": return pd.Series(masks.any(axis=0).astype(int),index=df.index)
            if aggregation=="hit_count": return pd.Series(masks.sum(axis=0).astype(int),index=df.index)
        raise ValueError(f"Unsupported rebuild feature_type: {kind}")


def build_feature_frame(df: pd.DataFrame, features: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame({row["feature_name"]: FeatureGenerator.rebuild(df, row) for row in features}, index=df.index)
