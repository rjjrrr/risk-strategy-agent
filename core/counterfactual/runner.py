from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from core.model_agent.models import ModelTrainer, temporal_split

from .evaluator import decide_counterfactual, delta_metrics, experiment_confidence
from .schemas import CounterfactualExperiment, utc_now

PREPROCESSING_VERSION = "counterfactual-preprocess-v1"


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")).encode()).hexdigest()


class FeatureCounterfactualRunner:
    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self, *, dataset_id: str, frame: pd.DataFrame, target_field: str, time_field: str,
        feature: dict, feature_values: pd.Series, baseline_features: list[str], model_type: str,
        experiment_type: str = "FEATURE_ADD", params: dict[str, Any] | None = None, seed: int = 42,
    ) -> CounterfactualExperiment:
        if target_field in baseline_features or time_field in baseline_features:
            baseline_features = [x for x in baseline_features if x not in {target_field, time_field}]
        feature_name = str(feature["feature_name"])
        if experiment_type == "FEATURE_ADD":
            baseline = sorted(set(baseline_features) - {feature_name})
            challenger = baseline + [feature_name]
        elif experiment_type == "FEATURE_REMOVE":
            baseline = sorted(set(baseline_features) | {feature_name})
            challenger = [x for x in baseline if x != feature_name]
        else:
            raise ValueError(f"Unsupported experiment type: {experiment_type}")
        if not baseline or not challenger:
            raise ValueError("Counterfactual feature pools cannot be empty")
        unknown = sorted(set(baseline + challenger) - set(frame.columns) - {feature_name})
        if unknown:
            raise ValueError(f"Baseline fields missing: {unknown}")
        work = frame.copy()
        work[feature_name] = pd.Series(feature_values, index=work.index)
        dev_idx, oot_idx = temporal_split(work, time_field)
        if len(dev_idx) < 20 or len(oot_idx) < 10:
            raise ValueError("Insufficient temporal DEV/OOT rows")
        y = pd.to_numeric(work[target_field], errors="coerce").astype(int)
        if y.loc[dev_idx].nunique() < 2 or y.loc[oot_idx].nunique() < 2:
            raise ValueError("DEV and OOT must both contain GOOD and BAD")
        params = {**(params or {}), "random_state": seed}
        params_hash = stable_hash(params)
        split_hash = stable_hash({"dev": [str(x) for x in dev_idx], "oot": [str(x) for x in oot_idx]})
        split_id = f"SPLIT_{split_hash[:12]}"
        pool_version = stable_hash({"baseline": baseline, "challenger": challenger})[:16]
        trainer = ModelTrainer(self.output_dir)
        experiment_id = f"CF_{uuid.uuid4().hex[:12]}"
        before = trainer.train(model_type, work.loc[dev_idx, baseline], y.loc[dev_idx], work.loc[oot_idx, baseline], y.loc[oot_idx], f"{experiment_id}_before", params)
        after = trainer.train(model_type, work.loc[dev_idx, challenger], y.loc[dev_idx], work.loc[oot_idx, challenger], y.loc[oot_idx], f"{experiment_id}_after", params)
        delta = delta_metrics(before["metrics"], after["metrics"])
        decision = decide_counterfactual(before["metrics"], after["metrics"], delta)
        return CounterfactualExperiment(
            experiment_id=experiment_id, feature_id=feature["feature_id"],
            feature_version=str(feature.get("version") or feature.get("feature_version") or "1.0"),
            hypothesis_id=feature.get("hypothesis_id"), dataset_id=dataset_id,
            experiment_type=experiment_type, baseline_state_id=f"STATE_{experiment_id}_BEFORE",
            challenger_state_id=f"STATE_{experiment_id}_AFTER", model_type=model_type,
            baseline_features=baseline, challenger_features=challenger, changed_features=[feature_name],
            model_params=params, model_params_hash=params_hash, split_id=split_id, split_hash=split_hash,
            seed=seed, preprocessing_version=PREPROCESSING_VERSION, feature_pool_version=pool_version,
            metrics_before=before["metrics"], metrics_after=after["metrics"], delta_metrics=delta,
            consistency_checks={"same_split": True, "same_seed": True, "same_params": True, "only_feature_pool_changed": len(set(baseline) ^ set(challenger)) == 1},
            decision=decision, confidence=experiment_confidence(len(oot_idx), decision, delta),
            artifacts={"baseline_model": before["model_path"], "challenger_model": after["model_path"]},
            finished_at=utc_now(),
        )
