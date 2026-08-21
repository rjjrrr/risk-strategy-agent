"""Generate deterministic Phase 1-4 diagnostic datasets and ground truth."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test_artifacts" / "phase45_diagnostic"
DATASETS = OUT / "datasets"
ROWS = 20_000
BASE_SEED = 45_000


def base_frame(case_number: int) -> tuple[pd.DataFrame, np.random.Generator]:
    rng = np.random.default_rng(BASE_SEED + case_number)
    frame = pd.DataFrame({
        "application_id": [f"C{case_number:02d}_{i:06d}" for i in range(ROWS)],
        "is_old": np.zeros(ROWS, dtype=int),
        "create_time": pd.date_range("2023-01-01", periods=ROWS, freq="h"),
        "base_feature": rng.normal(size=ROWS),
    })
    return frame, rng


def target_from_score(score: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    probability = 1 / (1 + np.exp(-score))
    return (rng.random(len(score)) < probability).astype(int)


def save_case(case_id: str, description: str, frame: pd.DataFrame, ground_truth: dict, expected: dict, records: list[dict]) -> None:
    path = DATASETS / case_id
    path.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path / "data.csv", index=False)
    metadata = {"case_id": case_id, "description": description, "rows": len(frame), "seed": BASE_SEED + int(case_id[:2]), "ground_truth": ground_truth, "expected_result": expected}
    (path / "ground_truth.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    records.append(metadata)


def main() -> None:
    DATASETS.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []

    frame, rng = base_frame(1); frame["signal_feature"] = rng.normal(size=ROWS); frame["target7"] = target_from_score(.45*frame.base_feature+1.8*frame.signal_feature, rng)
    save_case("01_strong_signal", "Stable strong feature", frame, {"signal":"stable_positive"}, {"validation":"PROMISING","counterfactual":"POSITIVE","credit":"POSITIVE"}, records)

    frame, rng = base_frame(2); frame["x1"] = rng.normal(size=ROWS); frame["x2"] = rng.normal(size=ROWS); frame["target7"] = target_from_score(2*frame.x1*frame.x2+2*frame.x1, rng)
    save_case("02_nonlinear_interaction", "Weak marginal x2 with nonlinear x1 interaction", frame, {"relationship":"interaction"}, {"validation":"EXPLORATORY","lr":"NEUTRAL","lgbm":"POSITIVE"}, records)

    frame, rng = base_frame(3); frame["pure_noise_feature"] = rng.normal(size=ROWS); frame["target7"] = target_from_score(.8*frame.base_feature, rng)
    save_case("03_pure_noise", "Independent noise feature", frame, {"independent":True}, {"counterfactual":["NEUTRAL","NEGATIVE"],"positive_high":False}, records)

    frame, rng = base_frame(4); frame["feature_A"] = rng.normal(size=ROWS); frame["feature_B"] = frame.feature_A+rng.normal(0,.005,ROWS); frame["target7"] = target_from_score(1.4*frame.feature_A, rng)
    save_case("04_redundant", "Near-duplicate feature", frame, {"spearman_min":.95}, {"novelty":"LOW","validation":"REVIEW","credit_positive_high":False}, records)

    frame, rng = base_frame(5); frame["flip_feature"] = rng.normal(size=ROWS); split=int(ROWS*.7); score=np.empty(ROWS); score[:split]=1.8*frame.flip_feature[:split]; score[split:]=-1.8*frame.flip_feature[split:]; frame["target7"] = target_from_score(score+.2*frame.base_feature, rng)
    save_case("05_dev_oot_flip", "DEV positive and OOT reversed", frame, {"dev_direction":"positive","oot_direction":"negative"}, {"counterfactual":"UNSTABLE","hypothesis_not_supported":True}, records)

    frame, rng = base_frame(6); split=int(ROWS*.7); frame["drift_feature"] = np.r_[rng.normal(0,1,split),rng.normal(4,1,ROWS-split)]; frame["target7"] = target_from_score(.8*frame.base_feature, rng)
    save_case("06_extreme_drift", "Severe DEV/OOT feature drift", frame, {"psi_min":.25}, {"warning":"EXTREME_DRIFT","lr_eligible":False}, records)

    frame, rng = base_frame(7); frame["user_id"]=[f"u{i%3000}" for i in range(ROWS)]; frame["device_id"]=[f"d{i%500}" for i in range(ROWS)]; frame["application_time"]=frame.create_time; offsets=rng.integers(-36,37,ROWS); frame["event_time"]=frame.application_time+pd.to_timedelta(offsets,unit="h"); frame["future_bad_signal"]=(offsets>=0).astype(int); frame["target7"]=target_from_score(.5*frame.base_feature, rng)
    save_case("07_future_leakage", "Future event and post-application signal attack", frame, {"strict_condition":"event_time < application_time","future_rows":int((offsets>=0).sum())}, {"leakage_status":"LEAKAGE_RISK","future_in_history":0}, records)

    frame, rng = base_frame(8); frame=frame[["application_id","is_old","create_time"]]; frame["income"]=rng.lognormal(8, .4, ROWS); frame["device_risk"]=rng.choice(["RED","AMBER","GREEN"],ROWS); frame["province"]=rng.choice(["P1","P2","P3"],ROWS); frame["target7"]=rng.binomial(1,.2,ROWS)
    save_case("08_missing_field", "Proposal references fake_credit_score", frame, {"available_fields":["income","device_risk","province"]}, {"compiler_status":"INVALID_SOURCE_FIELD","generated":False}, records)

    frame, rng = base_frame(9); frame["monthly_income"]=rng.lognormal(8,.45,ROWS); frame["device_risk_level"]=rng.choice(["RED","AMBER","GREEN"],ROWS,p=[.15,.3,.55]); frame["target7"]=target_from_score((frame.monthly_income<3000)*.8+(frame.device_risk_level=="RED")*1.2, rng)
    save_case("09_composable", "Controlled IF and BOOLEAN_AND feature", frame, {"dsl":"IF(BOOLEAN_AND(LE(monthly_income,3000),EQ(device_risk_level,'RED')),1,0)"}, {"compiler_status":"COMPOSABLE_DSL","execute":True,"rebuild":True}, records)

    frame, rng = base_frame(10); frame["x"]=rng.normal(size=ROWS); frame["target7"]=rng.binomial(1,.2,ROWS)
    save_case("10_malicious", "Malicious formula corpus", frame, {"expressions":["__import__","open","lambda","df[x]","import subprocess","eval","exec"]}, {"all":"INVALID_EXPRESSION","executed":False}, records)

    frame, rng = base_frame(11); frame["target7"]=rng.binomial(1,.2,ROWS)
    save_case("11_context_explosion", "Large context source cardinality", frame, {"messages":200,"rules":200,"features":200,"hypotheses":100,"experiments":200,"profiles":300}, {"within_budget":True,"top_k":True,"dedup":True}, records)

    frame, rng = base_frame(12); frame["signal_feature"]=rng.normal(size=ROWS); frame["target7"]=target_from_score(frame.signal_feature, rng)
    save_case("12_duplicate_experiment", "Same feature/model/params/split/seed twice", frame, {"signature":"identical"}, {"second":"DUPLICATE_EXPERIMENT","retrained":False}, records)

    frame, rng = base_frame(13); frame["signal_feature"]=rng.normal(size=ROWS); frame["target7"]=target_from_score(frame.signal_feature, rng)
    save_case("13_training_failure", "Technical model training failure", frame, {"failure_type":"technical"}, {"experiment":"FAILED","negative_credit":False}, records)

    frame, rng = base_frame(14); frame["source_a"]=rng.normal(size=ROWS); frame["source_b"]=rng.normal(size=ROWS); frame["target7"]=target_from_score(frame.source_a, rng)
    save_case("14_rebuild_version", "Dataset mutation after feature generation", frame, {"v2_mutates":"source_a"}, {"v1_rebuild":True,"v2":"VERSION_MISMATCH"}, records)

    frame, rng = base_frame(15); frame[["F1","F2","F3","F4","F5","F6"]]=rng.normal(size=(ROWS,6)); frame["target7"]=target_from_score(frame.F1+frame.F2, rng)
    save_case("15_hypothesis_credit", "Multi-feature hypothesis aggregation", frame, {"H001":["POSITIVE","POSITIVE","NEUTRAL"],"H002":["NEGATIVE","UNSTABLE","NEGATIVE"]}, {"H001":"SUPPORTED","H002":"REJECTED"}, records)

    analysis_cases = [
        {"case_id":"A01","dataset_summary":{"fields":["base_feature","signal_feature","target7"],"scope":"NEW"},"variable_evidence":{"signal_feature":{"direction":"positive","lift":2.0}},"rules":[],"feature_history":[],"user_query":"Identify stable risk mechanisms","expected_semantic_direction":"signal_feature positive risk","expected_hypothesis_topic":"stable signal risk","forbidden_fields":["future_bad_signal","fake_credit_score"]},
        {"case_id":"A05","dataset_summary":{"fields":["base_feature","flip_feature","target7","create_time"],"scope":"NEW"},"variable_evidence":{"flip_feature":{"dev_direction":"positive","oot_direction":"negative"}},"rules":[],"feature_history":[],"user_query":"Diagnose temporal instability","expected_semantic_direction":"OOT reversal","expected_hypothesis_topic":"unstable temporal relationship","forbidden_fields":["future_bad_signal","fake_credit_score"]},
    ]
    (OUT / "ground_truth.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "analysis_cases.json").write_text(json.dumps(analysis_cases, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cases":len(records),"rows_per_case":ROWS,"output":str(DATASETS.relative_to(ROOT))},ensure_ascii=False))


if __name__ == "__main__":
    main()
