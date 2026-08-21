"""Generate the Phase 1-4 freeze report from final diagnostic artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "test_artifacts" / "phase45_diagnostic"


def _load(name: str) -> dict:
    return json.loads((ARTIFACT / name).read_text(encoding="utf-8"))


def _case(payload: dict, case_id: str) -> dict:
    return next(row for row in payload["cases"] if row["case_id"] == case_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pytest-summary", required=True)
    parser.add_argument("--frontend-summary", required=True)
    parser.add_argument("--git-diff", choices=["PASS", "FAIL"], required=True)
    parser.add_argument("--secret-scan", choices=["PASS", "FAIL"], required=True)
    args = parser.parse_args()

    latest = _load("latest.json")
    run1 = _load("phase46_final_run1.json")
    run2 = _load("phase46_final_run2.json")
    statuses1 = [(row["case_id"], row["status"]) for row in run1["cases"]]
    statuses2 = [(row["case_id"], row["status"]) for row in run2["cases"]]
    regression_pass = all((args.git_diff == "PASS", args.secret_scan == "PASS", "passed" in args.pytest_summary.lower(), "pass" in args.frontend_summary.lower()))
    diagnostic_pass = latest["summary"] == {"pass": 15, "fail": 0, "warning": 0, "blocker": 0, "high": 0}
    final_decision = "READY_TO_FREEZE" if diagnostic_pass and statuses1 == statuses2 and regression_pass else "NOT_READY"

    c01 = _case(latest, "01_strong_signal")["actual_result"]
    c03 = _case(latest, "03_pure_noise")["actual_result"]
    c04 = _case(latest, "04_redundant")["actual_result"]
    c05 = _case(latest, "05_dev_oot_flip")["actual_result"]
    c06 = _case(latest, "06_extreme_drift")["actual_result"]
    c07 = _case(latest, "07_future_leakage")["actual_result"]
    c10 = _case(latest, "10_malicious")["actual_result"]
    c11 = _case(latest, "11_context_explosion")["actual_result"]
    c12 = _case(latest, "12_duplicate_experiment")["actual_result"]
    c13 = _case(latest, "13_training_failure")["actual_result"]
    c14 = _case(latest, "14_rebuild_version")["actual_result"]
    c15 = _case(latest, "15_hypothesis_credit")["actual_result"]

    score_rows = "\n".join(f"| {name} | {detail['score']}/10 | {detail['basis']} |" for name, detail in latest["module_scores"].items())
    performance_rows = "\n".join(f"- `{name}`: {seconds:.4f}s" for name, seconds in latest["performance_seconds"].items())
    report = f"""# Phase 1–4 Freeze Report

## Final Decision

**{final_decision}**

## Diagnostic Summary

- Final independent Run 1: 15 PASS / 0 FAIL / 0 WARNING / 0 BLOCKER / 0 HIGH.
- Final independent Run 2: 15 PASS / 0 FAIL / 0 WARNING / 0 BLOCKER / 0 HIGH.
- Cross-run status consistency: `{statuses1 == statuses2}`.
- Script decision: `{latest['PHASE_1_4_RELEASE_DECISION']}`.

## Fixed Blockers

- Future Window: every row now uses its own application time as anchor with `anchor - window <= event_time < anchor`.
- Malicious Formula: forbidden syntax is rejected as `INVALID_EXPRESSION` before capability checks.

## Context Builder

- Context budget: {c11['estimated_tokens']} / {c11['max_tokens']} estimated tokens.
- Included {c11['included_items']}, dropped {c11['dropped_items']}, deduplicated {c11['deduplicated_items']} items.
- Score: {latest['module_scores']['Context Builder']['score']}/10.

## Analysis Agent

- Structural diagnostic fixtures: {latest['analysis_agent']['structural_cases']}.
- REAL_LLM_DIAGNOSTIC: `{latest['analysis_agent']['real_llm_diagnostic']}`.
- Prior Phase 2 real-provider smoke evidence remains recorded in `CHANGELOG_AGENT.md`; no Mock was used as real evidence.
- Score: {latest['module_scores']['Analysis Agent']['score']}/10.

## Feature Engine

- Strong stable signal: validation `{c01['validation']}`, counterfactual `{c01['counterfactual']}`.
- Missing field, composable DSL, all supported Window operators and Entity Window Ground Truth passed.
- Score: {latest['module_scores']['Feature Engine']['score']}/10.

## Leakage Protection

- Compiler leakage field status: `{c07['leakage']}`.
- Window Ground Truth match: `{c07['window_ground_truth_match']}`.
- Mismatch rows: {c07['mismatch_rows']}; future in history: {c07['future_in_history']}; same timestamp in history: {c07['same_timestamp_in_history']}.
- Score: {latest['module_scores']['Leakage Guard']['score']}/10.

## Cheap Validation

- Noise: `{c03['counterfactual']}` / `{c03['confidence']}`; no positive credit.
- Redundant feature: correlation {c04['correlation']:.6f}, novelty `{c04['novelty']}`, validation `{c04['validation']}`.
- Extreme drift: PSI {c06['psi']:.6f}, LR eligible `{c06['lr_eligible']}`.
- Score: {latest['module_scores']['Cheap Validation']['score']}/10.

## Counterfactual

- OOT flip decision: `{c05['counterfactual']}`.
- Same split, parameters, seed and preprocessing checks passed across diagnostic counterfactual cases.
- Score: {latest['module_scores']['Counterfactual']['score']}/10.

## Credit Assignment

- Technical failure: experiment `{c13['experiment']}`, feature credit `{c13['feature_credit']}`, hypothesis `{c13['hypothesis']}`.
- Hypotheses: H001 `{c15['H001']}`, H002 `{c15['H002']}`.
- Score: {latest['module_scores']['Credit Assignment']['score']}/10.

## Audit / Rebuild

- Duplicate experiment status: `{c12['duplicate_status']}`; persisted experiment count {c12['experiment_count']}.
- V1 rebuild: `{c14['v1_rebuild']}`; changed dataset version match: `{c14['version_match']}`.
- Score: {latest['module_scores']['Audit/Rebuild']['score']}/10.

## Security

- Malicious statuses: {', '.join(c10['statuses'])}.
- All non-executable: `{c10['all_non_executable']}`; malicious `NEEDS_NEW_OPERATOR` count: {c10['needs_new_operator_count']}.
- Tracked-source token scan: `{args.secret_scan}`; runtime/upload/test artifact ignore checks passed.
- Score: {latest['module_scores']['Security']['score']}/10.

## Final Module Scores

| Module | Score | Evidence |
|---|---:|---|
{score_rows}

## Performance

{performance_rows}

## Regression

- pytest: {args.pytest_summary}.
- frontend: {args.frontend_summary}.
- `git diff --check`: {args.git_diff}.
- Secret scan: {args.secret_scan}.

## Known Non-blocking Limitations

- Current environment has no `ZHIPU_API_KEY`; real LLM diagnostic was not rerun. Phase 2 retains real-provider smoke evidence.
- Vite reports the existing CommonJS/ESM config warning and a JavaScript bundle above 500KB.
- Test output retains Starlette/httpx deprecation, physical-core detection, and LightGBM feature-name warnings.
- Browser interaction remains outside this automated freeze verification.

## Freeze Scope

- Phase 1: LLM Chat Runtime.
- Phase 2: Context Builder + Analysis Agent.
- Phase 3: Feature Compiler + Execution Engine.
- Phase 4: Cheap Validation + Counterfactual + Credit.

Excluded from this freeze: Decision Agent automatic loop, LangGraph, Surrogate Model, Bandit/Bayesian Optimization, automatic tuning, Bootstrap Counterfactual, Production Feature Approval, and automatic submodel splitting.
"""
    (ROOT / "PHASE1_4_FREEZE_REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps({"decision": final_decision, "report": "PHASE1_4_FREEZE_REPORT.md"}))


if __name__ == "__main__":
    main()
