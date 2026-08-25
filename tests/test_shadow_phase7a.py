from pathlib import Path

from core.decision_agent.engine import DecisionEngine
from core.decision_agent.schemas import CandidateAction
from core.llm.prompts import PROMPTS
from core.shadow.manager import ShadowManager


def candidate(fid, priority, probability, *, ood=False, version="SV_7A"):
    return {
        "action_type": "TEST_FEATURE", "feature_ids": [fid], "priority": priority,
        "reason": f"test {fid}", "model_type": "LR", "feature_type": "RATIO",
        "semantic_domain": "APPLICATION", "surrogate_prediction": {
            "positive_probability": probability, "expected_delta_auc": probability / 100,
            "expected_delta_ks": probability / 50, "expected_delta_lift10": probability / 20,
            "surrogate_id": "S_7A", "surrogate_version": version,
            "training_dataset_hash": "train-hash", "feature_vector_hash": f"hash-{fid}",
            "uncertainty": "LOW", "out_of_distribution": ood,
        },
    }


def decision(decision_id="D1", selected="F1", rows=None):
    rows = rows or [candidate("F1", 9, .2), candidate("F2", 4, .99), candidate("F3", 3, .5)]
    return {"decision_id": decision_id, "diagnosis": "LOW_SIGNAL", "candidate_actions": rows,
            "selected_action": next(row for row in rows if row["feature_ids"][0] == selected)}


def record(manager, payload=None, source="REAL"):
    return manager.record_round(loop_id="L1", decision=payload or decision(), context_hash="context-hash",
                                dataset_id="DATASET", dataset_version="V1", memory_source=source)


def result(actual="POSITIVE", auc=.01):
    return {"decision": actual, "experiment_id": "EXP1", "delta_metrics": {
        "delta_oot_auc": auc, "delta_oot_ks": auc * 2, "delta_lift10": auc * 5,
    }, "feature_credit": {"direction": actual}, "hypothesis_credit": {"direction": actual}}


def memory_rows(count, source="TEST_FIXTURE"):
    return [{"experiment_memory_id": f"M{i}", "source": source,
             "counterfactual_decision": "POSITIVE" if i % 2 else "NEGATIVE"} for i in range(count)]


def test_shadow_prediction_record(tmp_path):
    manager = ShadowManager(tmp_path); output = record(manager); row = output["items"][0]
    assert row["shadow_id"].startswith("SH_") and row["context_hash"] == "context-hash"
    assert row["memory_source"] == "REAL" and row["shadow_only"] is True


def test_shadow_does_not_change_phase5_rank(tmp_path):
    manager = ShadowManager(tmp_path); output = record(manager)
    assert output["final_selected_candidate"] == "F1"
    assert [(x["candidate_id"], x["phase5_rank"]) for x in output["items"]] == [("F1", 1), ("F2", 2), ("F3", 3)]
    assert next(x for x in output["items"] if x["candidate_id"] == "F2")["shadow_rank"] == 1


def test_shadow_actual_reconcile(tmp_path):
    manager = ShadowManager(tmp_path); record(manager); output = manager.reconcile(decision_id="D1", result=result())
    row = next(x for x in manager.predictions.all() if x["candidate_id"] == "F1")
    assert output["reconciled"] == 1 and row["status"] == "EVALUATED" and row["actual_decision"] == "POSITIVE"


def test_unselected_no_fake_label(tmp_path):
    manager = ShadowManager(tmp_path); record(manager); manager.reconcile(decision_id="D1", result=result())
    unselected = [x for x in manager.predictions.all() if not x["execution_selected_by_phase5"]]
    assert all(x["status"] == "NOT_SELECTED" and x["actual_decision"] is None for x in unselected)
    assert len(manager.errors.all()) == 1


def test_shadow_wrong_prediction(tmp_path):
    manager = ShadowManager(tmp_path); rows = [candidate("F1", 9, .95), candidate("F2", 2, .2)]
    record(manager, decision(rows=rows)); before = manager.predictions.all()[0]["positive_probability"]
    manager.reconcile(decision_id="D1", result=result("NEGATIVE", -.02)); error = manager.errors.all()[0]
    assert error["classification_error"] is True and manager.predictions.all()[0]["positive_probability"] == before


def test_shadow_ood(tmp_path):
    manager = ShadowManager(tmp_path); rows = [candidate("F1", 9, .2), candidate("F2", 2, .9, ood=True)]
    output = record(manager, decision(rows=rows)); ood = output["items"][1]
    assert ood["status"] == "OOD" and ood["uncertainty"] == "HIGH" and ood["out_of_distribution"] is True


def test_real_synthetic_isolation(tmp_path):
    manager = ShadowManager(tmp_path); checkpoint = manager.checkpoints(memory_rows(10, "REAL") + memory_rows(1000, "SYNTHETIC"))
    assert checkpoint["real_total"] == 10 and checkpoint["real_usable"] == 10


def test_real_30_checkpoint(tmp_path):
    checkpoint = ShadowManager(tmp_path).checkpoints(memory_rows(30), fixture_mode=True)
    assert checkpoint["real_usable"] == 30 and checkpoint["status"] == "REAL_EXPERIMENTAL" and checkpoint["next_checkpoint"] == 100


def test_real_100_checkpoint(tmp_path):
    checkpoint = ShadowManager(tmp_path).checkpoints(memory_rows(100), fixture_mode=True)
    assert checkpoint["real_usable"] == 100 and checkpoint["status"] == "REAL_ACTIVE_CANDIDATE_EVALUATION"


def test_real_promotion_gate(tmp_path):
    manager = ShadowManager(tmp_path); evaluation = {"performance_drift": False, "windows": {"ALL_HISTORY": {
        "classification": {"auc": .66}, "regression": {"spearman": .31},
        "ranking": {"shadow_ndcg_at_10": .70, "phase5_ndcg_at_10": .65}}}}
    gate = manager.promotion_gate(memory_rows(100), evaluation, fixture_mode=True)
    assert gate["status"] == "ACTIVE_CANDIDATE" and gate["passed"] is True and gate["phase7a_can_affect_final"] is False
    poor = manager.promotion_gate(memory_rows(100), {"performance_drift": False, "windows": {"ALL_HISTORY": {
        "classification": {"auc": .5}, "regression": {"spearman": 0}, "ranking": {}}}}, fixture_mode=True)
    assert poor["status"] == "REAL_SURROGATE_NOT_USEFUL"


def test_performance_drift(tmp_path):
    manager = ShadowManager(tmp_path)
    for i in range(90):
        truth = i % 2 == 0; good = i < 60; probability = .9 if truth == good else .1
        payload = decision(f"D{i}", "F1", [candidate("F1", 9, probability)])
        record(manager, payload); manager.reconcile(decision_id=f"D{i}", result=result("POSITIVE" if truth else "NEGATIVE", .01 if truth else -.01))
    evaluation = manager.evaluation()
    assert evaluation["performance_drift"] is True and evaluation["drift_status"] == "SURROGATE_PERFORMANCE_DRIFT"


def test_prediction_version_trace(tmp_path):
    row = record(ShadowManager(tmp_path))["items"][0]
    assert row["surrogate_version"] == "SV_7A" and row["training_dataset_hash"] == "train-hash"


def test_shadow_decision_prompt_guard():
    prompt = " ".join(str(x) for x in PROMPTS.values())
    assert "SHADOW_ONLY" in prompt and "NOT_FOR_FINAL_DECISION" in prompt
    assert "MUST NOT use it to override deterministic Phase5 ranking" in prompt


def test_backend_final_selection_guard():
    first = CandidateAction(action_type="TEST_FEATURE", reason="phase5", feature_ids=["F1"], evidence_confidence="HIGH", expected_utility=-999)
    second = CandidateAction(action_type="TEST_FEATURE", reason="shadow", feature_ids=["F2"], evidence_confidence="LOW", positive_probability=.99, expected_utility=999)
    ranked = sorted([DecisionEngine._rank(first), DecisionEngine._rank(second)], key=lambda x: -x.priority)
    assert ranked[0].feature_ids == ["F1"]


def test_shadow_error_breakdown(tmp_path):
    manager = ShadowManager(tmp_path); record(manager); manager.reconcile(decision_id="D1", result=result("NEGATIVE", -.02))
    breakdown = manager.error_breakdown()
    assert breakdown["feature_type"]["RATIO"]["count"] == 1
    assert breakdown["semantic_domain"]["APPLICATION"]["error_rate"] == 0.0
