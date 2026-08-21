import json
import re
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "test_artifacts" / "phase45_diagnostic"


def test_phase45_datasets_and_ground_truth():
    truth = json.loads((ARTIFACT / "ground_truth.json").read_text(encoding="utf-8"))
    assert len(truth) >= 15
    for case in truth:
        data = ARTIFACT / "datasets" / case["case_id"] / "data.csv"
        metadata = ARTIFACT / "datasets" / case["case_id"] / "ground_truth.json"
        assert data.exists() and metadata.exists()
        assert len(pd.read_csv(data, usecols=["target7", "is_old", "create_time"])) >= 20_000
        assert case["ground_truth"] and case["expected_result"] and case["seed"]


def test_phase45_diagnostic_schema():
    result = json.loads((ARTIFACT / "latest.json").read_text(encoding="utf-8"))
    assert result["case_count"] >= 15
    assert result["PHASE_1_4_RELEASE_DECISION"] in {"READY_TO_FREEZE", "READY_WITH_MINOR_FIXES", "NOT_READY"}
    assert result["reproducibility"]["consistent"] is True
    required = {"case_id", "status", "ground_truth", "actual_result", "checks", "unexpected_behavior", "severity", "recommended_fix"}
    assert all(required <= set(case) for case in result["cases"])
    assert all(case["status"] in {"PASS", "FAIL", "WARNING"} for case in result["cases"])
    assert all(case["severity"] in {"BLOCKER", "HIGH", "MEDIUM", "LOW", "INFO"} for case in result["cases"])


def test_phase45_report_sections_and_no_secret():
    report = (ARTIFACT / "DIAGNOSTIC_REPORT.md").read_text(encoding="utf-8")
    for title in ("Overall Result", "Case Summary", "Blockers", "High Risk Issues", "Analysis Agent", "Context Builder", "Feature Compiler", "Window / Entity Features", "Cheap Validation", "Counterfactual", "Feature Credit", "Hypothesis Credit", "Rebuild", "Security", "Performance", "Recommendations"):
        assert f"## {title}" in report
    combined = report + (ARTIFACT / "latest.json").read_text(encoding="utf-8")
    assert re.search(r"\b[0-9a-fA-F]{32}\.[A-Za-z0-9_-]{12,}\b", combined) is None
    assert "REAL_LLM_DIAGNOSTIC" in report
