"""Run deterministic Phase 3 acceptance against the saved Phase 2 proposals.

The script makes no LLM call and executes no generated Python. Evidence is written
under the git-ignored ``test_artifacts/phase3_acceptance`` directory.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.feature_engine.compiler import FeatureCompiler
from core.feature_engine.executor import FeatureExecutor
from core.feature_engine.lineage import dataset_version
from core.feature_engine.normalizer import normalize_proposal
from core.feature_engine.rebuild import compare_values
from core.feature_engine.registry_adapter import FeatureRegistryAdapter
from core.feature_engine.schemas import FeatureSpec
from core.json_utils import sanitize_json


def compile_feature(spec: FeatureSpec, frame: pd.DataFrame, sources: set[str], governance=None):
    return FeatureCompiler().compile(
        spec,
        schema_fields=set(frame.columns),
        governance=governance or {},
        available_sources=sources,
    )


def execute_check(spec: FeatureSpec, plan, frame: pd.DataFrame, executor: FeatureExecutor) -> tuple[pd.Series, dict]:
    started = time.perf_counter()
    values = executor.execute(spec, plan, frame)
    elapsed = time.perf_counter() - started
    rebuilt = executor.execute(spec, plan, frame)
    matched, method = compare_values(values, rebuilt)
    return values, {
        "rows": len(values),
        "valid": int(values.notna().sum()),
        "seconds": round(elapsed, 6),
        "rebuild_match": matched,
        "comparison": method,
    }


def main() -> None:
    phase2_path = ROOT / "test_artifacts" / "phase2_acceptance" / "acceptance.json"
    source_path = ROOT / "test_artifacts" / "large_regression" / "01_mineable" / "source.csv"
    phase2 = json.loads(phase2_path.read_text(encoding="utf-8"))
    frame = pd.read_csv(source_path)
    current_version = dataset_version(frame)
    proposals = {item["feature_name"]: item for item in phase2["structured"]["feature_proposals"]}
    executor = FeatureExecutor()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "test_artifacts" / "phase3_acceptance" / stamp
    run_dir.mkdir(parents=True, exist_ok=True)

    proposal_results = {}
    for name in ("device_risk_weighted_score", "low_income_device_risk_combo"):
        feature_spec = normalize_proposal(proposals[name], phase2["dataset_id"], current_version)
        plan = compile_feature(feature_spec, frame, {"CURRENT_WIDE_TABLE"})
        values, execution = execute_check(feature_spec, plan, frame, executor)
        artifact = run_dir / f"{name}.npz"
        np.savez_compressed(artifact, values=values.to_numpy())
        feature = FeatureRegistryAdapter(run_dir / "registry").add_generated(
            feature_spec,
            plan,
            artifact_path=str(artifact),
            execution_id=f"ACCEPT_{name}",
        )
        proposal_results[name] = {
            "compiler_status": plan.compiler_status,
            "operators": plan.operators,
            "ast": plan.ast,
            "estimated_cost": plan.estimated_cost,
            "execution": execution,
            "feature_id": feature["feature_id"],
            "registry_status": feature["status"],
        }

    ratio_frame = frame.assign(
        query_cnt_7d=pd.to_numeric(frame["AppRiskVar__app_list_not_sys_num"], errors="coerce"),
        query_cnt_90d=pd.to_numeric(frame["AppRiskVar__app_list_not_sys_num"], errors="coerce")
        + pd.to_numeric(frame["AppRiskVar__app_list_sys_count"], errors="coerce"),
    )
    ratio_spec = FeatureSpec(
        feature_spec_id="FS_ACCEPT_RATIO",
        feature_name="query_acceleration_7d_90d",
        business_intent="7-day query count divided by 90-day query count",
        feature_type="RATIO",
        source_fields=["query_cnt_7d", "query_cnt_90d"],
        desired_logic="7日查询次数 / 90日查询次数",
        dsl_expression="SAFE_DIV(query_cnt_7d,query_cnt_90d)",
        dataset_id=phase2["dataset_id"],
        dataset_version=current_version,
    )
    ratio_plan = compile_feature(ratio_spec, ratio_frame, {"CURRENT_WIDE_TABLE"})
    _, ratio_execution = execute_check(ratio_spec, ratio_plan, ratio_frame, executor)

    events = pd.DataFrame(
        {
            "user_id": ["u1", "u2", "u3", "u1", "u4"],
            "device_id": ["d1", "d1", "d1", "d1", "d1"],
            "ip": ["ip1", "ip1", "ip1", "ip1", "ip1"],
            "create_time": pd.to_datetime(
                ["2026-01-01 00:00", "2026-01-01 00:00", "2026-01-01 12:00", "2026-01-02 01:00", "2026-02-15 00:00"]
            ),
        }
    )
    window_spec = FeatureSpec(
        feature_spec_id="FS_ACCEPT_WINDOW", feature_name="device_apply_cnt_24h", business_intent="prior device applications",
        feature_type="TIME_WINDOW_AGG", source_fields=["device_id", "create_time"], entity_key="device_id",
        application_time_field="create_time", time_window="24h", desired_logic="当前申请前24小时同设备申请次数",
        dsl_expression='COUNT_OVER_WINDOW(device_id,create_time,"24h")', required_data_sources=["APPLICATION_EVENT_TABLE"],
    )
    window_plan = compile_feature(window_spec, events, {"APPLICATION_EVENT_TABLE"})
    window_values = executor.execute(window_spec, window_plan, events)
    entity_spec = FeatureSpec(
        feature_spec_id="FS_ACCEPT_ENTITY", feature_name="ip_shared_user_cnt_30d", business_intent="prior distinct users per IP",
        feature_type="TIME_WINDOW_AGG", source_fields=["ip", "user_id", "create_time"], entity_key="ip",
        application_time_field="create_time", time_window="30d", desired_logic="当前申请前30天同IP不同用户数",
        dsl_expression='ENTITY_WINDOW_NUNIQUE(ip,user_id,create_time,"30d")', required_data_sources=["IP_RELATION_TABLE"],
    )
    entity_plan = compile_feature(entity_spec, events, {"IP_RELATION_TABLE"})
    entity_values = executor.execute(entity_spec, entity_plan, events)

    malicious = compile_feature(ratio_spec.model_copy(update={"dsl_expression": '__import__("os").system("x")'}), ratio_frame, {"CURRENT_WIDE_TABLE"})
    leakage = compile_feature(
        ratio_spec.model_copy(update={"feature_type": "COLUMN_TRANSFORM", "source_fields": ["overdue_count"], "dsl_expression": "overdue_count"}),
        frame,
        {"CURRENT_WIDE_TABLE"},
        {"overdue_count": {"decision": "SUSPECT_LEAKAGE", "semantic_type": "SUSPECT_LEAKAGE"}},
    )
    evidence = {
        "phase2_commit": "ad62237",
        "dataset_id": phase2["dataset_id"],
        "dataset_version": current_version,
        "source": str(source_path.relative_to(ROOT)),
        "rows": len(frame),
        "phase2_proposals": proposal_results,
        "ratio_regression": {"compiler_status": ratio_plan.compiler_status, **ratio_execution},
        "window_regression": {"compiler_status": window_plan.compiler_status, "values": window_values.tolist(), "strict_expected": [0, 0, 2, 1, 0]},
        "entity_regression": {"compiler_status": entity_plan.compiler_status, "values": entity_values.tolist(), "strict_expected": [0, 0, 2, 3, 0]},
        "security": {"malicious_formula": malicious.compiler_status, "leakage": leakage.compiler_status},
    }
    evidence["checks"] = {
        "phase2_proposals_compile": all(x["compiler_status"] == "COMPOSABLE_DSL" for x in proposal_results.values()),
        "phase2_proposals_rebuild": all(x["execution"]["rebuild_match"] for x in proposal_results.values()),
        "registry_generated_not_approved": all(x["registry_status"] == "GENERATED" for x in proposal_results.values()),
        "ratio": ratio_plan.executable and ratio_execution["rebuild_match"],
        "window_strict_history": window_values.tolist() == evidence["window_regression"]["strict_expected"],
        "entity_strict_history": entity_values.tolist() == evidence["entity_regression"]["strict_expected"],
        "malicious_blocked": malicious.compiler_status == "INVALID_EXPRESSION",
        "leakage_blocked": leakage.compiler_status == "LEAKAGE_RISK",
    }
    output = json.dumps(sanitize_json(evidence), ensure_ascii=False, indent=2, allow_nan=False)
    (run_dir / "acceptance.json").write_text(output, encoding="utf-8")
    latest = ROOT / "test_artifacts" / "phase3_acceptance" / "latest.json"
    latest.write_text(output, encoding="utf-8")
    print(json.dumps({"artifact": str(latest.relative_to(ROOT)), "checks": evidence["checks"]}, ensure_ascii=False))
    if not all(evidence["checks"].values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
