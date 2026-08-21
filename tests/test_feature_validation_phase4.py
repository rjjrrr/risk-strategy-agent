import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app import config
from backend.app.main import app
from backend.app.services import agent_chat_service, analysis_service, context_service, feature_validation_service
from core.analysis_state import new_state
from core.context import ContextRequest
from core.counterfactual.audit import CounterfactualRegistry, FeatureCreditRegistry, HypothesisCreditRegistry
from core.counterfactual.credit import build_feature_credit, build_hypothesis_credit
from core.counterfactual.evaluator import decide_counterfactual, delta_metrics
from core.counterfactual.runner import FeatureCounterfactualRunner
from core.feature_validation.audit import FeatureValidationRegistry
from core.feature_validation.eligibility import determine_eligibility
from core.feature_validation.iv import information_value
from core.feature_validation.novelty import feature_novelty
from core.feature_validation.psi import population_stability_index
from core.feature_validation.validator import FeatureCheapValidator
from core.llm.storage import ChatStore
from core.model_agent.registry import ExperimentRegistry, FeatureRegistry


def _feature(**changes):
    base = {
        "feature_id": "F_SIGNAL", "feature_name": "new_signal", "version": "1.0",
        "feature_type": "COLUMN_TRANSFORM", "source_fields": ["source_a"],
        "normalized_ast": "SAFE_DIV(source_a,source_b)", "semantic_domain": "BEHAVIOR",
        "human_formula": "new behavior signal", "business_intent": "detect risky behavior",
        "status": "GENERATED", "hypothesis_id": "H1",
    }
    return {**base, **changes}


def _validation_inputs(n=1000, seed=7):
    rng = np.random.default_rng(seed)
    values = pd.Series(rng.normal(size=n))
    target = pd.Series((values + rng.normal(0, 0.45, n) > 0.8).astype(int))
    dev = pd.Series(np.arange(n) < int(n * 0.7))
    oot = ~dev
    times = pd.Series(pd.date_range("2025-01-01", periods=n, freq="h"))
    return values, target, dev, oot, times


def _validate(values=None, target=None, existing=None, feature=None):
    if values is None:
        values, target, dev, oot, times = _validation_inputs()
    else:
        n = len(values); dev = pd.Series(np.arange(n) < int(n * 0.7)); oot = ~dev; times = pd.Series(pd.date_range("2025-01-01", periods=n, freq="h"))
    return FeatureCheapValidator().validate(
        feature=feature or _feature(), values=values, target=target, dataset_id="D1",
        dev_mask=dev, oot_mask=oot, times=times, existing_pool=existing,
        existing_registry=[], governance={},
    )


def test_feature_validation_metrics():
    result = _validate()
    metrics = result.metrics
    assert result.decision == "PROMISING"
    assert {"row_count", "valid_count", "valid_rate", "missing_rate", "unique_count", "distribution_summary", "bad_rate_pattern", "lift", "iv", "psi", "temporal_stability", "pearson_target", "spearman_target", "max_existing_correlation", "feature_novelty"} <= set(metrics)


def test_feature_validation_missing_denominator():
    values = pd.Series([1.0, 1.0, np.nan, np.nan])
    target = pd.Series([1, 0, 1, 1])
    result = _validate(values, target)
    assert result.metrics["valid_count"] == 2 and result.metrics["missing_count"] == 2
    assert result.metrics["bad_rate_pattern"]["base_bad_rate"] == 0.5


def test_iv():
    values = pd.Series([0] * 50 + [1] * 50)
    target = pd.Series([0] * 45 + [1] * 5 + [0] * 5 + [1] * 45)
    assert information_value(values, target) > 2


def test_psi():
    rng = np.random.default_rng(3)
    assert population_stability_index(pd.Series(rng.normal(0, 1, 1000)), pd.Series(rng.normal(3, 1, 1000))) >= 0.25


def test_feature_novelty():
    feature = _feature()
    novelty, reasons = feature_novelty(feature, [{**feature, "feature_id": "F_OLD"}], 0.99)
    assert novelty == "LOW" and {"SAME_NORMALIZED_AST", "HIGH_CORRELATION"} <= set(reasons)


def test_lr_eligibility():
    metrics = {"psi": 0.02, "max_existing_correlation": 0.4, "iv": 0.08, "missing_rate": 0.0, "warnings": []}
    lr, _, reasons = determine_eligibility(_feature(), metrics, "PROMISING")
    assert lr and "STABLE" in reasons["LR"]


def test_lgbm_eligibility():
    metrics = {"psi": 0.05, "max_existing_correlation": 0.98, "iv": 0.001, "missing_rate": 0.0, "warnings": []}
    lr, lgbm, _ = determine_eligibility(_feature(), metrics, "EXPLORATORY")
    assert not lr and lgbm


@pytest.fixture(scope="module")
def positive_counterfactual(tmp_path_factory):
    rng = np.random.default_rng(91); n = 1400
    frame = pd.DataFrame({"time": pd.date_range("2024-01-01", periods=n, freq="h"), "base": rng.normal(size=n)})
    signal = pd.Series(rng.normal(size=n))
    probability = 1 / (1 + np.exp(-(0.45 * frame["base"] + 1.8 * signal)))
    frame["target7"] = (rng.random(n) < probability).astype(int)
    return FeatureCounterfactualRunner(tmp_path_factory.mktemp("cf")).run(
        dataset_id="D1", frame=frame, target_field="target7", time_field="time",
        feature=_feature(), feature_values=signal, baseline_features=["base"], model_type="LR", seed=42,
    )


def test_counterfactual_same_split(positive_counterfactual):
    row = positive_counterfactual
    assert row.split_id.endswith(row.split_hash[:12]) and row.consistency_checks["same_split"] and row.consistency_checks["only_feature_pool_changed"] and row.baseline_features == ["base"] and row.challenger_features == ["base", "new_signal"]


def test_counterfactual_same_params(positive_counterfactual):
    row = positive_counterfactual
    assert row.seed == 42 and row.model_params["random_state"] == 42 and row.model_params_hash and row.consistency_checks["same_params"] and row.consistency_checks["same_seed"]


def test_counterfactual_positive(positive_counterfactual):
    assert positive_counterfactual.decision == "POSITIVE" and positive_counterfactual.delta_metrics["delta_oot_auc"] > 0.005


def _metrics(auc=0.65, ks=0.25, lift=1.8, gap=0.03, psi=0.05, count=5, dev_auc=0.68):
    return {"dev_auc": dev_auc, "oot_auc": auc, "dev_ks": ks + 0.02, "oot_ks": ks, "lift_at_5": lift + 0.1, "lift_at_10": lift, "lift_at_20": lift - 0.1, "train_oot_auc_gap": gap, "score_psi": psi, "feature_count": count}


def test_counterfactual_neutral():
    before, after = _metrics(), _metrics(auc=0.651, ks=0.252, lift=1.81, count=6)
    delta = delta_metrics(before, after)
    assert decide_counterfactual(before, after, delta) == "NEUTRAL"


def test_counterfactual_negative():
    before, after = _metrics(), _metrics(auc=0.63, ks=0.22, lift=1.7, count=6)
    assert decide_counterfactual(before, after, delta_metrics(before, after)) == "NEGATIVE"


def test_counterfactual_unstable():
    before, after = _metrics(dev_auc=0.68), _metrics(auc=0.64, dev_auc=0.72, gap=0.08, count=6)
    assert decide_counterfactual(before, after, delta_metrics(before, after)) == "UNSTABLE"


def test_feature_credit():
    experiment = {"feature_id": "F1", "model_type": "LGBM", "decision": "POSITIVE", "confidence": "HIGH", "experiment_type": "FEATURE_ADD", "delta_metrics": {"delta_score_psi": 0.0}}
    credit = build_feature_credit("F1", "LGBM", [experiment], {"metrics": {"psi": 0.05}})
    assert credit.overall_direction == "POSITIVE" and credit.performance_credit == "POSITIVE"


def test_hypothesis_credit():
    experiments = [{"hypothesis_id": "H1", "feature_id": f"F{i}", "decision": decision, "delta_metrics": {"delta_oot_auc": 0.01 if decision == "POSITIVE" else 0, "delta_oot_ks": 0.02, "delta_lift_10": 0.06}} for i, decision in enumerate(["POSITIVE", "POSITIVE", "NEUTRAL"])]
    credit = build_hypothesis_credit("H1", experiments)
    assert credit.support_status == "SUPPORTED" and len(credit.positive_features) == 2


def test_ablation():
    experiment = {"feature_id": "F1", "model_type": "LR", "decision": "NEUTRAL", "confidence": "HIGH", "experiment_type": "FEATURE_REMOVE", "delta_metrics": {"delta_score_psi": 0.0}}
    credit = build_feature_credit("F1", "LR", [experiment], {"metrics": {"psi": 0.02}})
    assert credit.simplification_candidate and credit.simplicity_credit == "POSITIVE"


def test_duplicate_experiment(tmp_path):
    registry = CounterfactualRegistry(tmp_path)
    registry.add({"experiment_id": "E1", "experiment_signature": "same", "decision": "NEUTRAL"})
    assert registry.duplicate("same")["experiment_id"] == "E1"


def test_failed_train_no_negative_credit():
    failed = {"feature_id": "F1", "model_type": "LR", "decision": "FAILED"}
    assert build_feature_credit("F1", "LR", [failed]) is None


def test_exploratory_lgbm_case(tmp_path):
    rng = np.random.default_rng(2026); n = 8000
    base = pd.Series(rng.normal(size=n)); candidate = pd.Series(rng.normal(size=n))
    probability = 1/(1+np.exp(-(2.0*base*candidate+2.0*base)))
    target = pd.Series((rng.random(n)<probability).astype(int))
    validation = _validate(candidate, target)
    frame = pd.DataFrame({"time": pd.date_range("2024-01-01", periods=n, freq="h"), "base": base, "target7": target})
    runner = FeatureCounterfactualRunner(tmp_path / "nonlinear")
    lr = runner.run(dataset_id="D2", frame=frame, target_field="target7", time_field="time", feature=_feature(), feature_values=candidate, baseline_features=["base"], model_type="LR")
    lgbm = runner.run(dataset_id="D2", frame=frame, target_field="target7", time_field="time", feature=_feature(), feature_values=candidate, baseline_features=["base"], model_type="LGBM")
    assert validation.decision == "EXPLORATORY" and lr.decision == "NEUTRAL" and lgbm.decision == "POSITIVE"


def test_redundant_case():
    values, target, _, _, _ = _validation_inputs()
    result = _validate(values, target, existing=pd.DataFrame({"old": values}))
    assert result.metrics["feature_novelty"] == "LOW" and result.decision == "REVIEW"


def test_drift_case():
    rng = np.random.default_rng(8); values = pd.Series(np.r_[rng.normal(0, 1, 700), rng.normal(4, 1, 300)]); target = pd.Series(rng.integers(0, 2, 1000))
    result = _validate(values, target)
    assert result.metrics["psi"] >= .25 and result.decision in {"REVIEW", "REJECTED"} and not result.lr_eligible


def test_hypothesis_supported_case():
    rows = [{"hypothesis_id": "H", "feature_id": f"F{i}", "decision": d, "delta_metrics": {}} for i, d in enumerate(["POSITIVE", "POSITIVE", "NEUTRAL"])]
    assert build_hypothesis_credit("H", rows).support_status == "SUPPORTED"


def test_hypothesis_rejected_case():
    rows = [{"hypothesis_id": "H", "feature_id": f"F{i}", "decision": d, "delta_metrics": {}} for i, d in enumerate(["NEGATIVE", "UNSTABLE", "NEGATIVE"])]
    assert build_hypothesis_credit("H", rows).support_status == "REJECTED"


@pytest.fixture
def phase4_env(tmp_path, monkeypatch):
    rng = np.random.default_rng(101); n = 900; did = "phase4-dataset"
    signal = rng.normal(size=n); base = rng.normal(size=n)
    probability = 1 / (1 + np.exp(-(0.3 * base + 1.7 * signal)))
    frame = pd.DataFrame({"__row_id__": range(n), "is_old": [0] * n, "target7": (rng.random(n) < probability).astype(int), "create_time": pd.date_range("2024-01-01", periods=n, freq="h"), "base": base})
    governance = pd.DataFrame([{"field": field, "semantic_type": "DATETIME" if field == "create_time" else "NORMAL_FEATURE", "decision": "KEEP"} for field in frame.columns])
    analysis_service.DATASETS[did] = {"df": frame, "governance": governance, "rules": [], "target": "target7", "segment_field": "is_old", "state": new_state(did, "phase4.csv", n, len(frame.columns))}
    root = tmp_path / "models"; monkeypatch.setattr(config, "MODEL_AGENT_DIR", root); monkeypatch.setattr(context_service, "CONTEXT_DIR", tmp_path / "contexts"); context_service.CONTEXT_DIR.mkdir(); context_service._cache.clear()
    artifact = tmp_path / "signal.npz"; np.savez_compressed(artifact, values=signal)
    feature = _feature(artifact_path=str(artifact), source_fields=[], normalized_ast="FIELD(new_signal)")
    FeatureRegistry(root / did).add(feature)
    chat = ChatStore(tmp_path / "chat.sqlite3"); monkeypatch.setattr(agent_chat_service, "store", chat)
    yield did, feature, chat
    analysis_service.DATASETS.pop(did, None)


def test_phase4_api(phase4_env):
    did, feature, _ = phase4_env; client = TestClient(app)
    validation = client.post(f"/api/feature-validation/{feature['feature_id']}/run", json={"dataset_id": did, "time_field": "create_time"})
    assert validation.status_code == 200 and validation.json()["decision"] == "PROMISING"
    blocked = client.post(f"/api/counterfactual/feature/{feature['feature_id']}", json={"dataset_id": did, "model_type": "LR", "user_confirmed": False})
    assert blocked.status_code == 400
    result = client.post(f"/api/counterfactual/feature/{feature['feature_id']}", json={"dataset_id": did, "model_type": "LR", "time_field": "create_time", "user_confirmed": True})
    assert result.status_code == 200 and result.json()["decision"] == "POSITIVE"
    assert result.json()["baseline_features"] != result.json()["challenger_features"]


def test_context_credit_summary(phase4_env):
    did, feature, chat = phase4_env; root = config.MODEL_AGENT_DIR / did
    FeatureValidationRegistry(root).add({"validation_id": "FV1", "feature_id": feature["feature_id"], "decision": "PROMISING", "lr_eligible": True, "lgbm_eligible": True, "metrics": {"valid_rate": 1, "lift": 2, "iv": .2, "psi": .02, "feature_novelty": "HIGH", "max_existing_correlation": .1}, "warnings": []})
    FeatureCreditRegistry(root).add({"credit_id": "FC1", "feature_id": feature["feature_id"], "model_type": "LR", "overall_direction": "POSITIVE"})
    HypothesisCreditRegistry(root).add({"credit_id": "H1", "hypothesis_id": "H1", "support_status": "SUPPORTED"})
    CounterfactualRegistry(root).add({"experiment_id": "CF1", "feature_id": feature["feature_id"], "model_type": "LR", "decision": "POSITIVE", "delta_metrics": {"delta_oot_auc": .01}})
    ExperimentRegistry(root).add({"experiment_id": "CF1", "feature_id": feature["feature_id"], "model_type": "LR", "decision": "POSITIVE", "split_hash": "secret-detail", "metrics_before": {"large": "payload"}})
    conversation = chat.create_conversation(dataset_id=did, agent_type="ANALYSIS_AGENT")
    bundle = context_service.build(ContextRequest(conversation_id=conversation["conversation_id"], dataset_id=did), chat)
    assert {"FEATURE_VALIDATION", "FEATURE_CREDIT", "HYPOTHESIS_CREDIT", "COUNTERFACTUAL_HISTORY"} <= set(bundle.sources_used)
    history = next(item for item in bundle.items if item.source_type == "COUNTERFACTUAL_HISTORY")
    assert "latest" in history.content and "total_experiments" in history.content
    assert all(item.source_id != "CF1" for item in bundle.items if item.source_type == "EXPERIMENT_HISTORY")


def test_frontend_phase4_contract():
    page = Path("frontend/src/pages/FeatureEnginePage.tsx").read_text(encoding="utf-8")
    assert all(text in page for text in ("Run Validation", "Test in LR", "Test in LightGBM", "Same Split: YES", "Same Params: YES", "Feature Credit"))
