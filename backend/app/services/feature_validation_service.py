from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.counterfactual.audit import (
    CounterfactualRegistry,
    FeatureCreditRegistry,
    FeatureMarginalGainRegistry,
    HypothesisCreditRegistry,
    RemoveFeatureProposalRegistry,
)
from core.counterfactual.credit import build_feature_credit, build_hypothesis_credit
from core.counterfactual.runner import FeatureCounterfactualRunner, stable_hash
from core.counterfactual.schemas import FeatureMarginalGain
from core.feature_validation.audit import FeatureValidationRegistry
from core.feature_validation.validator import FeatureCheapValidator
from core.model_agent.models import temporal_split
from core.model_agent.registry import ExperimentRegistry, FeatureRegistry, HypothesisRegistry, utc_now

from .. import config
from . import context_service
from .analysis_service import DATASETS

DEFAULT_PARAMS = {
    "LR": {"penalty": "l2", "C": 1.0},
    "LGBM": {"n_estimators": 160, "learning_rate": 0.04, "num_leaves": 15, "max_depth": 5, "min_child_samples": 80, "subsample": 0.8, "colsample_bytree": 0.8, "reg_alpha": 0.1, "reg_lambda": 1.0},
}
MAX_COUNTERFACTUAL_EXPERIMENTS_PER_FEATURE = {"LR": 1, "LGBM": 1}


def _root(dataset_id: str) -> Path:
    root = config.MODEL_AGENT_DIR / dataset_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def _dataset(dataset_id: str) -> dict[str, Any]:
    if dataset_id not in DATASETS:
        raise KeyError(f"Dataset not loaded: {dataset_id}")
    return DATASETS[dataset_id]


def _find(rows: list[dict], key: str, value: str) -> dict:
    found = next((row for row in rows if row.get(key) == value), None)
    if not found:
        raise KeyError(value)
    return found


def _feature(dataset_id: str, feature_id: str) -> dict:
    return _find(FeatureRegistry(_root(dataset_id)).all(), "feature_id", feature_id)


def _values(feature: dict, index: pd.Index) -> pd.Series:
    path = Path(str(feature.get("artifact_path", "")))
    if not path.exists():
        raise ValueError("Feature artifact is unavailable")
    with np.load(path, allow_pickle=True) as data:
        array = data["values"]
    if len(array) != len(index):
        raise ValueError("Feature artifact row count does not match dataset")
    return pd.Series(array, index=index, name=feature["feature_name"])


def _new_mask(ds: dict[str, Any]) -> pd.Series:
    frame = ds["df"]
    segment = ds.get("segment_field") or ds.get("state", {}).get("config", {}).get("segment_field", "is_old")
    if segment not in frame:
        return pd.Series(True, index=frame.index)
    return frame[segment].map(lambda value: value == 0 or str(value).upper() == "NEW")


def _time_field(ds: dict[str, Any], requested: str | None = None) -> str:
    frame = ds["df"]
    candidates = [requested, ds.get("state", {}).get("config", {}).get("application_time_field"), "create_time", "apply_create_time"]
    field = next((str(item) for item in candidates if item and item in frame), None)
    if not field:
        raise ValueError("Application time field is required for temporal DEV/OOT validation")
    return field


def _governance(ds: dict[str, Any]) -> dict[str, dict]:
    rows = ds.get("governance")
    if rows is None:
        return {}
    records = rows.to_dict("records") if hasattr(rows, "to_dict") else rows
    return {str(row.get("field")): row for row in records}


def _baseline_features(ds: dict[str, Any], requested: list[str] | None = None) -> list[str]:
    frame, governance = ds["df"], _governance(ds)
    target = ds.get("target") or "target7"
    segment = ds.get("segment_field") or "is_old"
    if requested is not None:
        missing = sorted(set(requested) - set(frame.columns))
        if missing:
            raise ValueError(f"Baseline fields missing: {missing}")
        return [field for field in requested if field not in {target, segment, "__row_id__"}]
    blocked_types = {"DATETIME", "ID", "TARGET", "SUSPECT_LEAKAGE", "POST_LOAN_FEATURE", "EXISTING_MODEL_SCORE"}
    result = []
    for field in frame.columns:
        row = governance.get(str(field), {})
        if field in {target, segment, "__row_id__"} or row.get("decision") in {"SUSPECT_LEAKAGE", "EXCLUDE"} or row.get("semantic_type") in blocked_types:
            continue
        if frame[field].nunique(dropna=True) <= 1:
            continue
        result.append(str(field))
    return result[:30]


def run_validation(dataset_id: str, feature_id: str, time_field: str | None = None) -> dict:
    ds, root = _dataset(dataset_id), _root(dataset_id)
    feature = _feature(dataset_id, feature_id)
    if feature.get("status") not in {"GENERATED", "VALIDATED", "REJECTED"}:
        raise ValueError("Only generated features can be validated")
    frame = ds["df"]
    target_field = ds.get("target") or "target7"
    mask = _new_mask(ds) & frame[target_field].isin([0, 1])
    new = frame.loc[mask].copy()
    values = _values(feature, frame.index).loc[mask]
    time_name = _time_field(ds, time_field)
    dev_idx, oot_idx = temporal_split(new, time_name)
    dev_mask = pd.Series(new.index.isin(dev_idx), index=new.index)
    oot_mask = pd.Series(new.index.isin(oot_idx), index=new.index)
    pool_names = _baseline_features(ds)
    existing_pool = new[pool_names].select_dtypes(include=[np.number]) if pool_names else None
    result = FeatureCheapValidator().validate(
        feature=feature, values=values, target=new[target_field], dataset_id=dataset_id,
        dev_mask=dev_mask, oot_mask=oot_mask, times=new[time_name], existing_pool=existing_pool,
        existing_registry=FeatureRegistry(root).all(), governance=_governance(ds),
    ).model_dump()
    FeatureValidationRegistry(root).add(result)
    status = "REJECTED" if result["decision"] == "REJECTED" else "VALIDATED"
    FeatureRegistry(root).update(
        feature_id, status=status, validation_result=result, validation_status=result["decision"],
        lr_eligible=result["lr_eligible"], lgbm_eligible=result["lgbm_eligible"],
    )
    context_service._cache.clear()
    return result


def validation(dataset_id: str, feature_id: str) -> dict:
    row = FeatureValidationRegistry(_root(dataset_id)).latest_for_feature(feature_id)
    if not row:
        raise KeyError(feature_id)
    return row


def validations(dataset_id: str) -> list[dict]:
    return FeatureValidationRegistry(_root(dataset_id)).all()


def _signature(feature: dict, model_type: str, experiment_type: str, baseline: list[str], params: dict, split_hash: str, seed: int) -> str:
    return stable_hash({
        "feature_id": feature["feature_id"], "feature_version": feature.get("version") or feature.get("feature_version"),
        "model_type": model_type, "experiment_type": experiment_type, "baseline_features": sorted(baseline),
        "params": params, "split_hash": split_hash, "seed": seed,
    })


def run_counterfactual(
    dataset_id: str, feature_id: str, model_type: str, *, experiment_type: str = "FEATURE_ADD",
    baseline_features: list[str] | None = None, time_field: str | None = None, seed: int = 42,
    user_confirmed: bool = False,
) -> dict:
    if not user_confirmed:
        raise ValueError("Explicit user confirmation is required")
    model_type = model_type.upper()
    if model_type not in {"LR", "LGBM"}:
        raise ValueError("model_type must be LR or LGBM")
    ds, root = _dataset(dataset_id), _root(dataset_id)
    feature = _feature(dataset_id, feature_id)
    validation_row = validation(dataset_id, feature_id)
    eligible_key = "lr_eligible" if model_type == "LR" else "lgbm_eligible"
    if not validation_row.get(eligible_key):
        raise ValueError(f"Feature is not {model_type} eligible")
    frame = ds["df"]
    target_field, time_name = ds.get("target") or "target7", _time_field(ds, time_field)
    mask = _new_mask(ds) & frame[target_field].isin([0, 1]) & pd.to_datetime(frame[time_name], errors="coerce").notna()
    new = frame.loc[mask].copy()
    values = _values(feature, frame.index).loc[mask]
    baseline = _baseline_features(ds, baseline_features)
    dev_idx, oot_idx = temporal_split(new, time_name)
    split_hash = stable_hash({"dev": [str(x) for x in dev_idx], "oot": [str(x) for x in oot_idx]})
    params = dict(DEFAULT_PARAMS[model_type])
    signature = _signature(feature, model_type, experiment_type, baseline, params, split_hash, seed)
    registry = CounterfactualRegistry(root)
    duplicate = registry.duplicate(signature)
    if duplicate:
        return {**duplicate, "duplicate": True, "duplicate_status": "DUPLICATE_EXPERIMENT"}
    prior = [row for row in registry.all() if row.get("feature_id") == feature_id and row.get("model_type") == model_type and row.get("experiment_type") == experiment_type and row.get("decision") != "FAILED"]
    if len(prior) >= MAX_COUNTERFACTUAL_EXPERIMENTS_PER_FEATURE[model_type]:
        raise ValueError("MAX_COUNTERFACTUAL_EXPERIMENTS_PER_FEATURE reached")
    try:
        result = FeatureCounterfactualRunner(root / "counterfactual_models").run(
            dataset_id=dataset_id, frame=new, target_field=target_field, time_field=time_name,
            feature=feature, feature_values=values, baseline_features=baseline, model_type=model_type,
            experiment_type=experiment_type, params=params, seed=seed,
        ).model_dump()
        result["experiment_signature"] = signature
        registry.add(result)
        ExperimentRegistry(root).add(result)
        delta = result["delta_metrics"]
        gain = FeatureMarginalGain(
            gain_id=f"{feature_id}::{model_type}", feature_id=feature_id,
            feature_version=str(feature.get("version") or feature.get("feature_version") or "1.0"),
            model_type=model_type, experiment_id=result["experiment_id"], conclusion=result["decision"],
            confidence=result["confidence"], **delta,
        ).model_dump()
        gain_registry = FeatureMarginalGainRegistry(root)
        gain_registry.update(gain["gain_id"], **gain) if gain_registry.get(gain["gain_id"]) else gain_registry.add(gain)
        _update_credits(root, feature, result, validation_row)
        if experiment_type == "FEATURE_REMOVE" and result["decision"] == "NEUTRAL":
            proposal = {
                "proposal_id": f"RFP_{uuid.uuid4().hex[:12]}", "proposal_type": "REMOVE_FEATURE_PROPOSAL",
                "feature_id": feature_id, "experiment_id": result["experiment_id"], "status": "PENDING_HUMAN_APPROVAL",
                "reason": "Remove ablation was neutral; feature is a simplification candidate.",
            }
            RemoveFeatureProposalRegistry(root).add(proposal)
            result["remove_feature_proposal"] = proposal
        context_service._cache.clear()
        return result
    except Exception as exc:
        failed = {
            "experiment_id": f"CF_FAILED_{uuid.uuid4().hex[:10]}", "feature_id": feature_id,
            "feature_version": str(feature.get("version") or feature.get("feature_version") or "1.0"),
            "hypothesis_id": feature.get("hypothesis_id"), "dataset_id": dataset_id,
            "experiment_type": experiment_type, "model_type": model_type, "baseline_features": baseline,
            "challenger_features": [], "changed_features": [feature["feature_name"]], "model_params": params,
            "model_params_hash": stable_hash({**params, "random_state": seed}), "split_id": f"SPLIT_{split_hash[:12]}",
            "split_hash": split_hash, "seed": seed, "preprocessing_version": "counterfactual-preprocess-v1",
            "feature_pool_version": "", "metrics_before": {}, "metrics_after": {}, "delta_metrics": {},
            "consistency_checks": {"same_split": True, "same_seed": True, "same_params": True, "only_feature_pool_changed": True},
            "decision": "FAILED", "confidence": "LOW", "error": str(exc), "experiment_signature": signature,
            "finished_at": utc_now(),
        }
        registry.add(failed)
        ExperimentRegistry(root).add(failed)
        raise


def _update_credits(root: Path, feature: dict, result: dict, validation_row: dict) -> None:
    experiments = CounterfactualRegistry(root).all()
    credit = build_feature_credit(feature["feature_id"], result["model_type"], experiments, validation_row)
    if credit:
        row = credit.model_dump()
        row["credit_id"] = f"{feature['feature_id']}::{result['model_type']}"
        registry = FeatureCreditRegistry(root)
        existing = registry.get(row["credit_id"])
        registry.update(row["credit_id"], **row) if existing else registry.add(row)
    hypothesis_id = feature.get("hypothesis_id")
    if hypothesis_id:
        hypothesis = build_hypothesis_credit(hypothesis_id, experiments).model_dump()
        hypothesis["credit_id"] = hypothesis_id
        registry_h = HypothesisCreditRegistry(root)
        existing_h = registry_h.get(hypothesis_id)
        registry_h.update(hypothesis_id, **hypothesis) if existing_h else registry_h.add(hypothesis)
        hypotheses = HypothesisRegistry(root)
        if hypotheses.get(hypothesis_id):
            hypotheses.update(hypothesis_id, status=hypothesis["support_status"], hypothesis_credit=hypothesis)


def experiment(dataset_id: str, experiment_id: str) -> dict:
    return _find(CounterfactualRegistry(_root(dataset_id)).all(), "experiment_id", experiment_id)


def experiments(dataset_id: str) -> list[dict]:
    return CounterfactualRegistry(_root(dataset_id)).all()


def feature_credit(dataset_id: str, feature_id: str) -> list[dict]:
    return [row for row in FeatureCreditRegistry(_root(dataset_id)).all() if row.get("feature_id") == feature_id]


def hypothesis_credit(dataset_id: str, hypothesis_id: str) -> dict:
    row = HypothesisCreditRegistry(_root(dataset_id)).get(hypothesis_id)
    if row:
        return row
    return build_hypothesis_credit(hypothesis_id, CounterfactualRegistry(_root(dataset_id)).all()).model_dump()
