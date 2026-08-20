"""Generate and run three large deterministic Risk Strategy Agent regression datasets."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.analysis_service import get_dataset, get_state, register_upload, run_all  # noqa: E402

SUITE_DIR = ROOT / "test_artifacts" / "large_regression"
N_ROWS = 60_000
SEED = 20260820


def _common_frame(rng: np.random.Generator, n: int) -> pd.DataFrame:
    start = np.datetime64("2024-01-01")
    days = rng.integers(0, 730, n)
    return pd.DataFrame(
        {
            "application_id": [f"APP{i:08d}" for i in range(n)],
            "is_old": np.where(np.arange(n) % 2 == 0, 0, 2),
            "create_time": start + days.astype("timedelta64[D]"),
            "apply_create_time": start + days.astype("timedelta64[D]") + np.timedelta64(2, "h"),
            "detail_create_time": start + days.astype("timedelta64[D]") + np.timedelta64(4, "h"),
        }
    )


def make_mineable(n: int = N_ROWS) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    df = _common_frame(rng, n)
    risk_score = np.clip(rng.normal(55, 18, n), 0, 100)
    overdue_count = rng.poisson(1.2, n)
    income = np.clip(rng.lognormal(np.log(6500), 0.55, n), 800, 60_000)
    device_risk = rng.choice(["GREEN", "AMBER", "RED"], n, p=[0.65, 0.25, 0.10])
    province = rng.choice(["P1", "P2", "P3", "P4", "P5"], n)
    logit = (
        -2.65
        + 2.2 * (risk_score >= 78)
        + 1.35 * (overdue_count >= 3)
        + 1.45 * (device_risk == "RED")
        + 1.05 * (income <= 3300)
        + 0.65 * (province == "P5")
        + 0.20 * (df["is_old"].to_numpy() == 2)
    )
    probability = 1 / (1 + np.exp(-logit))
    df["target7"] = (rng.random(n) < probability).astype(int)
    df["risk_score"] = np.round(risk_score, 4)
    df["overdue_count"] = overdue_count
    df["monthly_income"] = np.round(income, 2)
    df["device_risk_level"] = device_risk
    df["province_group"] = province
    df["AppRiskVar__app_list_not_sys_num"] = rng.integers(0, 100, n)
    df["AppRiskVar__app_list_sys_count"] = rng.integers(0, 80, n)
    for i in range(12):
        df[f"noise_numeric_{i:02d}"] = rng.normal(i, 1 + i / 10, n)
    for i in range(6):
        df[f"noise_category_{i:02d}"] = rng.choice(["A", "B", "C", "D"], n)
    return df


def make_unmineable(n: int = N_ROWS) -> pd.DataFrame:
    rng = np.random.default_rng(SEED + 1)
    df = _common_frame(rng, n)
    target = np.tile(np.array([0, 0, 0, 0, 1], dtype=int), n // 5 + 1)[:n]
    rng.shuffle(target)
    df["target7"] = target
    df["risk_score"] = rng.uniform(0, 100, n)
    df["overdue_count"] = rng.integers(0, 8, n)
    df["monthly_income"] = rng.lognormal(np.log(6500), 0.5, n)
    df["device_risk_level"] = rng.choice(["GREEN", "AMBER", "RED"], n, p=[0.65, 0.25, 0.10])
    df["province_group"] = rng.choice(["P1", "P2", "P3", "P4", "P5"], n)
    df["AppRiskVar__app_list_not_sys_num"] = rng.integers(0, 100, n)
    df["AppRiskVar__app_list_sys_count"] = rng.integers(0, 80, n)
    for i in range(12):
        df[f"noise_numeric_{i:02d}"] = rng.normal(i, 1 + i / 10, n)
    for i in range(6):
        df[f"noise_category_{i:02d}"] = rng.choice(["A", "B", "C", "D"], n)
    return df


def make_clusterable(n: int = N_ROWS) -> pd.DataFrame:
    """Create several different fields that intentionally hit the same customers."""
    rng = np.random.default_rng(SEED + 2)
    df = _common_frame(rng, n)
    signal = rng.uniform(0, 1, n)
    high_risk = signal >= 0.80
    probability = np.where(high_risk, 0.58, 0.045) + np.where(df["is_old"].to_numpy() == 2, 0.01, 0)
    df["target7"] = (rng.random(n) < probability).astype(int)

    # Monotonic transforms preserve quantile membership and therefore hit masks.
    df["behavior_metric_a"] = signal
    df["behavior_metric_b"] = signal * 10 + 7
    df["behavior_metric_c"] = signal * 1000 + 3
    band = np.where(high_risk, "HIGH", "NORMAL")
    df["customer_band_a"] = band
    df["customer_band_b"] = band
    df["customer_band_c"] = band
    for i in range(8):
        df[f"independent_noise_{i:02d}"] = rng.normal(i, 1, n)
    return df


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def run_case(name: str, frame: pd.DataFrame, expect_rules: bool, expect_clustered: bool = False) -> dict:
    case_dir = SUITE_DIR / name
    result_dir = case_dir / "results"
    internal_dir = result_dir / "internal"
    case_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    source_path = case_dir / "source.csv"
    frame.to_csv(source_path, index=False, encoding="utf-8-sig")

    dataset_id, _ = register_upload(source_path.name, source_path.read_bytes())
    run_all(dataset_id, force=True)
    ds = get_dataset(dataset_id)
    state = get_state(dataset_id)
    rules = ds["rules"]
    stage = state["stages"]["rule_groups"]

    backend_results = ROOT / "backend" / "outputs" / dataset_id
    for filename in ("candidate_rules.csv", "variable_governance.csv", "rule_report.md"):
        shutil.copy2(backend_results / filename, result_dir / filename)
    shutil.copytree(ROOT / "backend" / "uploads" / dataset_id / "internal", internal_dir, dirs_exist_ok=True)

    segment_summary = {}
    for segment in ("NEW", "OLD"):
        matrix = np.load(internal_dir / f"jaccard_{segment.lower()}.npz")["matrix"]
        upper = np.triu(matrix, 1)
        summaries = [x for x in stage.get("summaries", []) if x.get("segment") == segment]
        segment_summary[segment] = {
            "raw_rules": sum(r.get("segment") == segment for r in rules),
            "hit_masks": sum(r.get("segment") == segment and r.get("_mask_global") is not None for r in rules),
            "matrix_shape": list(matrix.shape),
            "strong_edges": int((upper >= 0.90).sum()),
            "similar_edges": int((upper >= 0.80).sum()),
            "groups": len(summaries),
            "singleton_groups": sum(x.get("rule_count") == 1 for x in summaries),
        }

    datetime_fields = {"create_time", "apply_create_time", "detail_create_time"}
    numeric_equality = [
        r for r in rules
        if r.get("field") in frame.columns
        and pd.api.types.is_numeric_dtype(frame[r["field"]])
        and frame[r["field"]].nunique(dropna=True) > 10
        and "==" in str(r.get("rule"))
    ]
    forbidden_rules = {
        "AppRiskVar__app_list_not_sys_num == 53",
        "AppRiskVar__app_list_sys_count == 17",
        "AppRiskVar__app_list_sys_count == 48",
    }
    summary = {
        "case": name,
        "dataset_id": dataset_id,
        "rows": len(frame),
        "columns": len(frame.columns),
        "target_bad_rate": float(frame["target7"].mean()),
        "stage_status": state["stage_status"],
        "segments": segment_summary,
        "total_rules": len(rules),
        "representative_rules": sum(r.get("is_representative", True) for r in rules),
        "rule_groups": stage.get("group_count", 0),
        "compression_ratio": stage.get("compression_ratio", 0),
        "largest_group_size": max((x.get("rule_count", 0) for x in stage.get("summaries", [])), default=0),
        "largest_group": max(stage.get("summaries", []), key=lambda x: x.get("rule_count", 0), default=None),
        "datetime_candidate_rules": sum(r.get("field") in datetime_fields for r in rules),
        "numeric_high_card_equality_rules": len(numeric_equality),
        "forbidden_example_rules": sorted({r.get("rule") for r in rules} & forbidden_rules),
        "oot_counts": {
            segment: {
                status: sum(r.get("segment") == segment and r.get("oot_status") == status for r in rules)
                for status in ("STRONG", "WEAK", "FAILED", "NOT_AVAILABLE")
            }
            for segment in ("NEW", "OLD")
        },
    }
    assert all(v == "SUCCESS" for v in state["stage_status"].values()), summary
    assert summary["datetime_candidate_rules"] == 0, summary
    assert summary["numeric_high_card_equality_rules"] == 0, summary
    assert not summary["forbidden_example_rules"], summary
    assert (summary["total_rules"] > 0) == expect_rules, summary
    if expect_clustered:
        assert summary["representative_rules"] < summary["total_rules"], summary
        assert summary["rule_groups"] < summary["total_rules"], summary
        assert summary["compression_ratio"] > 0, summary
        assert summary["largest_group_size"] >= 3, summary
        assert sum(v["strong_edges"] for v in segment_summary.values()) > 0, summary
    for segment, values in segment_summary.items():
        assert values["raw_rules"] == values["hit_masks"], (segment, values)
        assert values["matrix_shape"] == [values["raw_rules"], values["raw_rules"]], (segment, values)
        if values["raw_rules"]:
            assert values["groups"] > 0, (segment, values)

    (result_dir / "analysis_state.json").write_text(json.dumps(_json_safe(state), ensure_ascii=False, indent=2), encoding="utf-8")
    (result_dir / "summary.json").write_text(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    SUITE_DIR.mkdir(parents=True, exist_ok=True)
    summaries = [
        run_case("01_mineable", make_mineable(), expect_rules=True),
        run_case("02_unmineable", make_unmineable(), expect_rules=False),
        run_case("03_clusterable", make_clusterable(), expect_rules=True, expect_clustered=True),
    ]
    report = ["# Large Regression Test Report", ""]
    for summary in summaries:
        report.extend(
            [
                f"## {summary['case']}",
                "",
                f"- Rows: {summary['rows']:,}",
                f"- Columns: {summary['columns']}",
                f"- Bad rate: {summary['target_bad_rate']:.4%}",
                f"- Rules: {summary['total_rules']}",
                f"- Rule groups: {summary['rule_groups']}",
                f"- Compression: {summary['compression_ratio']:.2%}",
                f"- Largest group size: {summary['largest_group_size']}",
                f"- NEW: {summary['segments']['NEW']}",
                f"- OLD: {summary['segments']['OLD']}",
                f"- DATETIME candidate rules: {summary['datetime_candidate_rules']}",
                f"- Numeric high-card equality rules: {summary['numeric_high_card_equality_rules']}",
                "",
            ]
        )
    (SUITE_DIR / "test_report.md").write_text("\n".join(report), encoding="utf-8")
    (SUITE_DIR / "suite_summary.json").write_text(json.dumps(_json_safe(summaries), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(_json_safe(summaries), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
