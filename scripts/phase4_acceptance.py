"""Run Phase 4 acceptance using the saved Phase 2 real-LLM proposal and 60k dataset."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.counterfactual.credit import build_feature_credit
from core.counterfactual.runner import FeatureCounterfactualRunner
from core.feature_engine.compiler import FeatureCompiler
from core.feature_engine.executor import FeatureExecutor
from core.feature_engine.lineage import dataset_version
from core.feature_engine.normalizer import normalize_proposal
from core.feature_validation.validator import FeatureCheapValidator
from core.json_utils import sanitize_json
from core.model_agent.models import temporal_split


def main() -> None:
    source = ROOT / "test_artifacts" / "large_regression" / "01_mineable" / "source.csv"
    phase2_file = ROOT / "test_artifacts" / "phase2_acceptance" / "acceptance.json"
    frame = pd.read_csv(source)
    phase2 = json.loads(phase2_file.read_text(encoding="utf-8"))
    proposal = next(x for x in phase2["structured"]["feature_proposals"] if x["feature_name"] == "device_risk_weighted_score")
    version = dataset_version(frame)
    spec = normalize_proposal(proposal, phase2["dataset_id"], version)
    plan = FeatureCompiler().compile(spec, schema_fields=set(frame.columns), available_sources={"CURRENT_WIDE_TABLE"})
    values = FeatureExecutor().execute(spec, plan, frame)
    feature = {
        "feature_id": "F_PHASE4_DEVICE_RISK", "feature_name": spec.feature_name, "version": "1.0",
        "feature_type": spec.feature_type, "source_fields": spec.source_fields, "normalized_ast": plan.normalized_ast,
        "semantic_domain": spec.semantic_domain, "human_formula": plan.human_formula,
        "business_intent": spec.business_intent, "hypothesis_id": spec.hypothesis_id,
    }
    mask = (frame["is_old"] == 0) & frame["target7"].isin([0, 1])
    new, new_values = frame.loc[mask].copy(), values.loc[mask]
    dev_idx, oot_idx = temporal_split(new, "create_time")
    dev_mask = pd.Series(new.index.isin(dev_idx), index=new.index)
    oot_mask = pd.Series(new.index.isin(oot_idx), index=new.index)
    baseline = ["monthly_income", "province_group", "AppRiskVar__app_list_not_sys_num", "AppRiskVar__app_list_sys_count", "noise_numeric_00", "noise_numeric_01"]
    validation = FeatureCheapValidator().validate(
        feature=feature, values=new_values, target=new["target7"], dataset_id=phase2["dataset_id"],
        dev_mask=dev_mask, oot_mask=oot_mask, times=new["create_time"],
        existing_pool=new[[x for x in baseline if pd.api.types.is_numeric_dtype(new[x])]], existing_registry=[], governance={},
    ).model_dump()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "test_artifacts" / "phase4_acceptance" / stamp
    experiment = FeatureCounterfactualRunner(run_dir / "models").run(
        dataset_id=phase2["dataset_id"], frame=new, target_field="target7", time_field="create_time",
        feature=feature, feature_values=new_values, baseline_features=baseline, model_type="LGBM", seed=42,
    ).model_dump()
    credit = build_feature_credit(feature["feature_id"], "LGBM", [experiment], validation)
    evidence = {
        "phase3_commit": "00d6aa6", "source": str(source.relative_to(ROOT)), "rows": len(frame), "new_rows": len(new),
        "feature": feature, "compiler_status": plan.compiler_status, "validation": validation,
        "counterfactual": experiment, "feature_credit": credit.model_dump() if credit else None,
        "checks": {
            "compiled": plan.executable, "validation_completed": validation["decision"] in {"PROMISING", "EXPLORATORY", "REVIEW", "REJECTED"},
            "temporal_split": experiment["split_id"].endswith(experiment["split_hash"][:12]),
            "same_params": bool(experiment["model_params_hash"]), "single_factor": len(set(experiment["challenger_features"])-set(experiment["baseline_features"])) == 1,
            "credit_created": credit is not None,
        },
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    output = json.dumps(sanitize_json(evidence), ensure_ascii=False, indent=2, allow_nan=False)
    (run_dir / "acceptance.json").write_text(output, encoding="utf-8")
    latest = ROOT / "test_artifacts" / "phase4_acceptance" / "latest.json"
    latest.write_text(output, encoding="utf-8")
    print(json.dumps({"artifact": str(latest.relative_to(ROOT)), "validation": validation["decision"], "counterfactual": experiment["decision"], "delta_oot_auc": experiment["delta_metrics"]["delta_oot_auc"], "checks": evidence["checks"]}, ensure_ascii=False))
    if not all(evidence["checks"].values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
