from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.decision_agent.context import build_decision_context
from core.experiment_memory.aggregator import CreditAggregator
from core.experiment_memory.audit import ExperimentMemoryRegistry
from core.experiment_memory.builder import ExperimentMemoryBuilder
from core.experiment_memory.retriever import ExperimentRetriever
from core.surrogate.meta_features import FORBIDDEN_FUTURE_FIELDS, build_meta_features
from core.surrogate.ranking import CandidateRanker
from core.surrogate.trainer import SurrogateTrainer


def memory_row(i: int, *, dataset="A", feature_type="WINDOW_COUNT", domain="DEVICE", model="LGBM", outcome=None, psi=.05):
    positive = (i % 5) < (4 if (feature_type == "WINDOW_COUNT" and model == "LGBM") or (feature_type == "RATIO" and model == "LR") else 2)
    outcome = outcome or ("UNSTABLE" if psi >= .25 and i % 3 else "POSITIVE" if positive else "NEGATIVE")
    gain = .012 + (i % 3) * .001 if outcome == "POSITIVE" else -.004
    return {"experiment_id": f"E_{dataset}_{i}_{feature_type}_{model}", "timestamp": (datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(hours=i)).isoformat(), "dataset_id": dataset, "dataset_version": f"{dataset}_v1", "data_source": "TEST", "segment": "NEW", "model_type": model, "action_type": "TEST_FEATURE", "hypothesis_id": f"H_{i%7}", "feature_ids": [f"F_{i}"], "feature_types": [feature_type], "semantic_domains": [domain], "evidence_types": ["TEMPORAL_PATTERN"], "baseline_state_id": "S0", "baseline_metrics": {"oot_auc": .66, "oot_ks": .3, "lift_10": 2.0, "auc_gap": .03}, "result_metrics": {"oot_auc": .66+gain}, "delta_metrics": {"delta_oot_auc": gain, "delta_oot_ks": gain*2, "delta_lift10": gain*10}, "counterfactual_decision": outcome, "action_outcome": outcome, "feature_credit": {}, "hypothesis_credit": {}, "diagnosis_before": "LOW_SIGNAL", "state_after": f"S{i}", "cost": 1, "runtime": .2, "human_approval": False, "success": outcome == "POSITIVE", "validation_metrics": {"decision": "PROMISING", "iv": .08, "psi": psi, "valid_rate": .98, "feature_novelty": "HIGH", "max_existing_correlation": .2}, "feature_count_before": 10, "source": "SYNTHETIC", "experiment_signature": f"SIG_{dataset}_{i}_{feature_type}_{model}"}


def history(n=220):
    rows=[]
    for i in range(n):
        if i % 4 == 0: rows.append(memory_row(i, feature_type="RATIO", domain="INCOME", model="LR"))
        elif i % 4 == 1: rows.append(memory_row(i, feature_type="RATIO", domain="INCOME", model="LGBM"))
        elif i % 4 == 2: rows.append(memory_row(i, feature_type="WINDOW_COUNT", domain="DEVICE", model="LGBM"))
        else: rows.append(memory_row(i, feature_type="WINDOW_COUNT", domain="DEVICE", model="LGBM", psi=.4))
    return rows


def test_experiment_memory_builder(tmp_path):
    registry=ExperimentMemoryRegistry(tmp_path); builder=ExperimentMemoryBuilder(registry)
    result=builder.build([{"experiment_id":"E1","feature_id":"F1","model_type":"LR","decision":"POSITIVE","created_at":"2026-01-01","metrics_before":{},"metrics_after":{},"delta_metrics":{"delta_oot_auc":.01}}],dataset_id="D",features=[{"feature_id":"F1","feature_type":"RATIO","semantic_domain":"INCOME","hypothesis_id":"H1"}])
    assert result["inserted"]==1 and registry.all()[0]["feature_types"]==["RATIO"]


def test_memory_no_raw_rows(tmp_path):
    row=memory_row(1); assert not ({"raw_rows","df","dataframe"}&set(row))
    assert "raw" not in str(ExperimentMemoryRegistry(tmp_path).path.name)


def test_memory_dedup(tmp_path):
    registry=ExperimentMemoryRegistry(tmp_path); row=memory_row(1)
    assert registry.add_deduplicated(row)[1] and not registry.add_deduplicated({**row,"experiment_id":"OTHER"})[1]


def test_feature_type_credit():
    credit=CreditAggregator().aggregate(history(40),"FEATURE_TYPE")
    assert next(x for x in credit if x["value"]=="WINDOW_COUNT")["experiment_count"]>0


def test_semantic_domain_credit():
    assert {x["value"] for x in CreditAggregator().aggregate(history(20),"SEMANTIC_DOMAIN")}=={"DEVICE","INCOME"}


def test_model_specific_credit():
    rows=CreditAggregator().aggregate(history(80),"FEATURE_TYPE",by_model=True)
    lr=next(x for x in rows if x["value"]=="RATIO" and x["model_type"]=="LR")
    gbm=next(x for x in rows if x["value"]=="RATIO" and x["model_type"]=="LGBM")
    assert lr["smoothed_positive_rate"]>gbm["smoothed_positive_rate"]


def test_failed_not_negative_credit():
    rows=[memory_row(1,outcome="POSITIVE"),memory_row(2,outcome="FAILED")]
    credit=CreditAggregator().aggregate(rows,"FEATURE_TYPE")[0]
    assert credit["sample_count"]==1 and credit["negative_count"]==0 and credit["failed_count"]==1


def test_credit_confidence_small_sample():
    credit=CreditAggregator().aggregate([memory_row(1,outcome="POSITIVE")],"FEATURE_TYPE")[0]
    assert credit["positive_rate"]==1 and credit["confidence"]=="LOW" and credit["smoothed_positive_rate"]<1


def test_meta_feature_no_future_result():
    meta=build_meta_features(memory_row(1))
    assert set(meta).isdisjoint(FORBIDDEN_FUTURE_FIELDS) and "delta_oot_auc" not in meta


def test_surrogate_insufficient_data(tmp_path):
    result=SurrogateTrainer(tmp_path).train(history(10),user_confirmed=True)
    assert result["status"]=="INSUFFICIENT_DATA" and result["reason"]=="SURROGATE_INSUFFICIENT_DATA"


def test_surrogate_training(tmp_path):
    result=SurrogateTrainer(tmp_path).train(history(),user_confirmed=True)
    assert result["status"]=="ACTIVE" and result["artifact"]


def test_surrogate_time_split(tmp_path):
    result=SurrogateTrainer(tmp_path).train(history(120),user_confirmed=True)
    assert result["metrics"]["split"]=="TIME_ORDERED_80_20"


def test_surrogate_prediction(tmp_path):
    trainer=SurrogateTrainer(tmp_path); trainer.train(history(),user_confirmed=True)
    prediction=trainer.predict({**memory_row(999),"counterfactual_decision":None,"delta_metrics":{}})
    assert 0<=prediction["positive_probability"]<=1 and len(prediction["feature_vector_hash"])==64


def test_candidate_ranking(tmp_path):
    trainer=SurrogateTrainer(tmp_path); rows=history(); trainer.train(rows,user_confirmed=True)
    candidates=[{"candidate_id":"C1","feature_type":"WINDOW_COUNT","semantic_domain":"DEVICE","model_type":"LGBM","dataset_id":"A","novelty":"HIGH"},{"candidate_id":"C2","feature_type":"RATIO","semantic_domain":"INCOME","model_type":"LGBM","dataset_id":"A","novelty":"MEDIUM"}]
    ranked=CandidateRanker(rows,trainer).rank(candidates)
    assert ranked[0]["priority"]>=ranked[1]["priority"] and ranked[0]["ranking_mode"]=="SURROGATE"


def test_exploration_new_domain(tmp_path):
    rows=history(120); trainer=SurrogateTrainer(tmp_path); trainer.train(rows,user_confirmed=True)
    ranked=CandidateRanker(rows,trainer).rank([{"candidate_id":"KNOWN","feature_type":"RATIO","semantic_domain":"INCOME","model_type":"LR","dataset_id":"A","novelty":"LOW"},{"candidate_id":"NEW","feature_type":"COMPOSITE","semantic_domain":"LOCATION","model_type":"LR","dataset_id":"A","novelty":"HIGH"}],opportunity_index=7)
    assert ranked[0]["candidate_id"]=="NEW" and ranked[0]["uncertainty"]=="HIGH" and ranked[0]["surrogate_prediction"]["out_of_distribution"]


def test_same_dataset_priority():
    rows=[memory_row(i,dataset="A",outcome="POSITIVE") for i in range(3)]+[memory_row(20,dataset="B",outcome="NEGATIVE")]
    similar=ExperimentRetriever(rows).similar({"dataset_id":"B","dataset_version":"B_v1","feature_type":"WINDOW_COUNT","semantic_domain":"DEVICE","model_type":"LGBM"})
    assert similar[0]["dataset_id"]=="B" and similar[0]["scope"]=="SAME_DATASET"


def test_prediction_wrong_feedback_update():
    before=CreditAggregator().aggregate([memory_row(i,outcome="POSITIVE") for i in range(4)],"FEATURE_TYPE")[0]["smoothed_positive_rate"]
    after=CreditAggregator().aggregate([memory_row(i,outcome="POSITIVE") for i in range(4)]+[memory_row(20,outcome="NEGATIVE")],"FEATURE_TYPE")[0]["smoothed_positive_rate"]
    assert after<before


def test_surrogate_fallback(tmp_path):
    ranked=CandidateRanker(history(10),SurrogateTrainer(tmp_path)).rank([{"candidate_id":"C","feature_type":"RATIO","semantic_domain":"INCOME","model_type":"LR","dataset_id":"A"}])
    assert ranked[0]["ranking_mode"]=="PHASE5_FALLBACK"


def test_decision_context_memory_budget():
    memory={"source":"EXPERIMENT_MEMORY","summary":{"total":1000},"similar":[{"id":i} for i in range(5)],"historical_winners":[{"id":i} for i in range(5)],"relevant_failures":[{"id":i} for i in range(5)],"aggregate_credit":{"feature_types":[{"id":i} for i in range(5)]}}
    context=build_decision_context({"experiment_memory":memory})["context"]["experiment_memory"]
    assert len(context["similar"])<=5 and len(context["historical_winners"])<=5 and len(context["relevant_failures"])<=5
