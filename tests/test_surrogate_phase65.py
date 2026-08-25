from __future__ import annotations

import copy

import pytest

from core.experiment_memory.aggregator import CreditAggregator
from core.surrogate.diagnostics import (audit_dataset, compare_models, feature_group_ablation,
                                        learning_curve, permutation_importance_report)
from core.surrogate.meta_features import META_FEATURES, build_meta_features
from core.surrogate.synthetic import GROUND_TRUTH_VERSION, generate_synthetic_v2
from core.surrogate.trainer import SurrogateTrainer
from core.surrogate.ranking import CandidateRanker


@pytest.fixture(scope="module")
def v2(): return generate_synthetic_v2(1200)


@pytest.fixture(scope="module")
def trained(v2,tmp_path_factory):
    return SurrogateTrainer(tmp_path_factory.mktemp("phase65_model")).train(v2,user_confirmed=True)


@pytest.fixture(scope="module")
def compared(v2): return compare_models(v2)


def test_surrogate_target_distribution(v2):
    target=audit_dataset(v2)["target_distribution"]
    assert 0<target["probability_positive"]["positive"]<len(v2) and target["delta_oot_auc"]["std"]>0 and "p99" in target["delta_oot_auc"]


def test_surrogate_oracle_baseline(compared):
    assert compared["models"]["OracleRule"]["auc"]>.60 and compared["ranking"]["Oracle"]["ndcg_at_10"]>compared["ranking"]["Random"]["ndcg_at_10"]


def test_surrogate_random_baseline(compared):
    assert compared["models"]["RandomPredictor"]["auc"]==.5


def test_time_split_distribution(v2):
    audit=audit_dataset(v2); assert audit["train_distribution"]["count"]==960 and audit["test_distribution"]["count"]==240 and "detected" in audit["temporal_distribution_shift"]


def test_random_vs_time_split(compared):
    assert compared["time_split_auc"] is not None and compared["random_split_auc"] is not None and compared["time_split_auc"]!=compared["random_split_auc"]


def test_no_id_memorization(v2):
    assert {"dataset_id","feature_id","hypothesis_id"}.isdisjoint(META_FEATURES) and audit_dataset(v2)["id_leakage"] is False


def test_meta_feature_ablation(v2):
    report=feature_group_ablation(v2[:500]); assert set(report["groups"])=={"FeatureMetadata","ValidationMetrics","BaselineModelMetrics","HistoricalCredit","Diagnosis","SemanticDomain","ModelType"} and permutation_importance_report(v2[:500])


def test_ranking_vs_random(trained):
    rank=trained["metrics"]["ranking"];assert rank["surrogate"]["ndcg_at_10"]>rank["random"]["ndcg_at_10"]


def test_ranking_vs_phase5(trained):
    rank=trained["metrics"]["ranking"];assert rank["surrogate"]["ndcg_at_10"]>=rank["phase5"]["ndcg_at_10"]


def test_calibration(trained):
    cal=trained["metrics"]["calibration"];assert cal["method"]=="PLATT" and cal["after"]["brier_score"]<=cal["before"]["brier_score"] and cal["after"]["ece"]<cal["before"]["ece"]


def test_ood_uncertainty(v2,tmp_path):
    trainer=SurrogateTrainer(tmp_path);trainer.train(v2,user_confirmed=True);p=trainer.predict({"candidate_id":"OOD","feature_type":"NEW_KIND","semantic_domain":"NEW_DOMAIN","model_type":"LR"})
    assert p["out_of_distribution"] and p["uncertainty"]=="HIGH" and p["nearest_experiment_distance"]>=0


def test_active_gate(trained):
    assert trained["status"]=="ACTIVE" and trained["metrics"]["active_gate"]["passed"]


def test_low_signal_fallback(v2,tmp_path):
    rows=[]
    for i,row in enumerate(v2[:300]):
        item=copy.deepcopy(row);item["counterfactual_decision"]="POSITIVE" if i%2 else "NEGATIVE";item["delta_metrics"]={"delta_oot_auc":0.001 if i%2 else -.001,"delta_oot_ks":0,"delta_lift10":0};rows.append(item)
    trainer=SurrogateTrainer(tmp_path);model=trainer.train(rows,user_confirmed=True);ranked=CandidateRanker(rows,trainer).rank([{"candidate_id":"C","feature_type":"RATIO","semantic_domain":"INCOME","model_type":"LR"}])
    assert model["status"] in {"DISABLED_LOW_SIGNAL","EXPERIMENTAL"} and ranked[0]["ranking_mode"]=="PHASE5_FALLBACK"


def test_synthetic_v2_ground_truth(v2):
    assert len(v2)>=1000 and all(x["ground_truth_function_version"]==GROUND_TRUTH_VERSION for x in v2) and "latent_expected_gain" not in build_meta_features(v2[0])


def test_learning_curve(v2):
    curve=learning_curve(v2,sizes=(30,50,100,200,500,1000));assert [x["sample_size"] for x in curve]==[30,50,100,200,500,1000] and all({"auc","spearman","ndcg_at_10"}<=set(x) for x in curve)


def test_wrong_prediction_retrain(v2,tmp_path):
    trainer=SurrogateTrainer(tmp_path);first=trainer.train(v2[:500],user_confirmed=True);before=CreditAggregator().aggregate(v2[:500],"FEATURE_TYPE")[0]["smoothed_positive_rate"]
    feedback=[]
    for i,row in enumerate(v2[500:620]):
        item=copy.deepcopy(row);item["counterfactual_decision"]="NEGATIVE";item["delta_metrics"]["delta_oot_auc"]=-.01;feedback.append(item)
    second=trainer.train(v2[:500]+feedback,user_confirmed=True);after=CreditAggregator().aggregate(v2[:500]+feedback,"FEATURE_TYPE")[0]["smoothed_positive_rate"]
    assert second["training_dataset_hash"]!=first["training_dataset_hash"] and after<before
