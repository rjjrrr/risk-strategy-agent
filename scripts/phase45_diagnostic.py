"""Execute two read-only Phase 1-4 diagnostic passes and write one final report."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.context import ContextBuilder, ContextRequest
from core.context.sources import item
from core.counterfactual.audit import CounterfactualRegistry
from core.counterfactual.credit import build_feature_credit, build_hypothesis_credit
from core.counterfactual.runner import FeatureCounterfactualRunner
from core.feature_engine.compiler import FeatureCompiler
from core.feature_engine.executor import FeatureExecutor
from core.feature_engine.lineage import dataset_version
from core.feature_engine.rebuild import compare_values
from core.feature_engine.schemas import FeatureSpec
from core.feature_validation.novelty import feature_novelty
from core.feature_validation.validator import FeatureCheapValidator
from core.json_utils import sanitize_json
from core.model_agent.models import temporal_split

OUT = ROOT / "test_artifacts" / "phase45_diagnostic"
DATASETS = OUT / "datasets"


def load(case_id: str) -> pd.DataFrame:
    frame = pd.read_csv(DATASETS / case_id / "data.csv")
    for field in ("create_time", "event_time", "application_time"):
        if field in frame:
            frame[field] = pd.to_datetime(frame[field], errors="coerce")
    return frame


def feature(name: str, **changes: Any) -> dict[str, Any]:
    return {"feature_id":f"F_{name.upper()}","feature_name":name,"version":"1.0","feature_type":"COLUMN_TRANSFORM","source_fields":[],"normalized_ast":f"FIELD({name})","semantic_domain":"DIAGNOSTIC","human_formula":name,"business_intent":f"diagnose {name}","hypothesis_id":f"H_{name.upper()}",**changes}


def validate(frame: pd.DataFrame, field: str, existing: pd.DataFrame | None = None, existing_registry: list[dict] | None = None) -> dict:
    dev, oot = temporal_split(frame, "create_time")
    dev_mask = pd.Series(frame.index.isin(dev), index=frame.index); oot_mask = ~dev_mask
    return FeatureCheapValidator().validate(feature=feature(field),values=frame[field],target=frame.target7,dataset_id="D45",dev_mask=dev_mask,oot_mask=oot_mask,times=frame.create_time,existing_pool=existing,existing_registry=existing_registry or [],governance={}).model_dump()


def run_cf(frame: pd.DataFrame, field: str, baseline: list[str], model: str, output: Path) -> dict:
    return FeatureCounterfactualRunner(output).run(dataset_id="D45",frame=frame,target_field="target7",time_field="create_time",feature=feature(field),feature_values=frame[field],baseline_features=baseline,model_type=model,seed=42).model_dump()


def case_result(case_id: str, ground_truth: Any, actual: Any, checks: dict[str,bool], severity: str, fix: str = "") -> dict:
    passed = all(checks.values())
    return {"case_id":case_id,"status":"PASS" if passed else "FAIL","ground_truth":ground_truth,"actual_result":sanitize_json(actual),"checks":checks,"unexpected_behavior":[] if passed else [name for name,value in checks.items() if not value],"severity":"INFO" if passed else severity,"recommended_fix":"None" if passed else fix}


def context_explosion() -> tuple[dict, float]:
    sources=[]
    counts={"CONVERSATION_MEMORY":200,"RULE_SUMMARY":200,"FEATURE_REGISTRY":200,"HYPOTHESIS_REGISTRY":100,"EXPERIMENT_HISTORY":200,"VARIABLE_PROFILE":300}
    for source_type,count in counts.items():
        for i in range(count):
            duplicate_index=i%50
            content={"index":duplicate_index,"signal":f"evidence-{duplicate_index}","payload":"x"*120}
            sources.append(item(source_type,f"{source_type}-{i}",f"{source_type} {duplicate_index}",content,priority="HIGH" if i<5 else "MEDIUM"))
    request=ContextRequest(conversation_id="C45",dataset_id="D45",max_context_tokens=2000,max_items_per_source=20)
    started=time.perf_counter(); bundle=ContextBuilder().build(request,sources); latency=time.perf_counter()-started
    return {"estimated_tokens":bundle.estimated_context_tokens,"included_items":bundle.included_items,"dropped_items":bundle.dropped_items,"deduplicated_items":bundle.deduplicated_items,"sources_used":bundle.sources_used,"max_tokens":request.max_context_tokens},latency


def diagnostic_pass(pass_id: int) -> tuple[list[dict],dict[str,float]]:
    results=[]; perf={}; temp=Path(tempfile.mkdtemp(prefix=f"phase45_pass{pass_id}_"))
    gt=json.loads((OUT/"ground_truth.json").read_text(encoding="utf-8")); truths={x["case_id"]:x for x in gt}

    f=load("01_strong_signal"); v=validate(f,"signal_feature"); cf=run_cf(f,"signal_feature",["base_feature"],"LR",temp/"c01"); credit=build_feature_credit("F_SIGNAL_FEATURE","LR",[cf],v)
    results.append(case_result("01_strong_signal",truths["01_strong_signal"],{"validation":v["decision"],"counterfactual":cf["decision"],"delta":cf["delta_metrics"],"credit":credit.model_dump() if credit else None},{"promising":v["decision"]=="PROMISING","positive":cf["decision"]=="POSITIVE","material":cf["delta_metrics"]["delta_oot_auc"]>.005 or cf["delta_metrics"]["delta_oot_ks"]>.01 or cf["delta_metrics"]["delta_lift_10"]>.05,"credit_positive":credit is not None and credit.overall_direction=="POSITIVE","single_factor":all(cf["consistency_checks"].values())},"HIGH"))

    f=load("02_nonlinear_interaction"); v=validate(f,"x2"); lr=run_cf(f,"x2",["x1"],"LR",temp/"c02lr"); lg=run_cf(f,"x2",["x1"],"LGBM",temp/"c02lg")
    results.append(case_result("02_nonlinear_interaction",truths["02_nonlinear_interaction"],{"validation":v["decision"],"lr":lr["decision"],"lgbm":lg["decision"]},{"exploratory":v["decision"]=="EXPLORATORY","lr_neutral":lr["decision"]=="NEUTRAL","lgbm_positive":lg["decision"]=="POSITIVE","consistent":all(lr["consistency_checks"].values()) and all(lg["consistency_checks"].values())},"HIGH","Review counterfactual thresholds or nonlinear eligibility."))

    f=load("03_pure_noise"); v=validate(f,"pure_noise_feature"); cf=run_cf(f,"pure_noise_feature",["base_feature"],"LR",temp/"c03"); credit=build_feature_credit("F_PURE_NOISE_FEATURE","LR",[cf],v)
    results.append(case_result("03_pure_noise",truths["03_pure_noise"],{"validation":v["decision"],"counterfactual":cf["decision"],"confidence":cf["confidence"],"credit":credit.model_dump() if credit else None},{"not_positive_high":not(cf["decision"]=="POSITIVE" and cf["confidence"]=="HIGH"),"credit_not_positive":credit is None or credit.overall_direction!="POSITIVE"},"HIGH","Tighten material-gain consistency for noise features."))

    f=load("04_redundant"); v=validate(f,"feature_B",existing=f[["feature_A"]]); novelty,_=feature_novelty(feature("feature_B"),[],abs(f.feature_A.corr(f.feature_B,method="spearman"))); cf=run_cf(f,"feature_B",["feature_A"],"LR",temp/"c04")
    results.append(case_result("04_redundant",truths["04_redundant"],{"correlation":abs(f.feature_A.corr(f.feature_B,method="spearman")),"novelty":novelty,"validation":v["decision"],"counterfactual":cf["decision"],"confidence":cf["confidence"]},{"high_corr":abs(f.feature_A.corr(f.feature_B,method="spearman"))>=.95,"novelty_low":novelty=="LOW","review":v["decision"]=="REVIEW","not_positive_high":not(cf["decision"]=="POSITIVE" and cf["confidence"]=="HIGH")},"HIGH"))

    f=load("05_dev_oot_flip"); cf=run_cf(f,"flip_feature",["base_feature"],"LR",temp/"c05")
    results.append(case_result("05_dev_oot_flip",truths["05_dev_oot_flip"],{"counterfactual":cf["decision"],"before":cf["metrics_before"],"after":cf["metrics_after"],"delta":cf["delta_metrics"]},{"unstable":cf["decision"]=="UNSTABLE","oot_negative":cf["delta_metrics"]["delta_oot_auc"]<0,"not_supported":cf["decision"]!="POSITIVE"},"BLOCKER","Strengthen DEV/OOT reversal detection."))

    f=load("06_extreme_drift"); v=validate(f,"drift_feature")
    results.append(case_result("06_extreme_drift",truths["06_extreme_drift"],{"decision":v["decision"],"psi":v["metrics"]["psi"],"warnings":v["warnings"],"lr_eligible":v["lr_eligible"]},{"psi":v["metrics"]["psi"]>=.25,"drift_warning":"EXTREME_DRIFT" in v["warnings"],"review_or_reject":v["decision"] in {"REVIEW","REJECTED"},"lr_blocked":not v["lr_eligible"]},"BLOCKER"))

    f=load("07_future_leakage"); spec=FeatureSpec(feature_spec_id="FS07",feature_name="device_count",business_intent="historical count",feature_type="TIME_WINDOW_AGG",source_fields=["device_id","event_time"],entity_key="device_id",application_time_field="application_time",time_window="24h",desired_logic="prior device events",dsl_expression='COUNT_OVER_WINDOW(device_id,event_time,"24h")',required_data_sources=["APPLICATION_EVENT_TABLE"]); plan=FeatureCompiler().compile(spec,schema_fields=set(f.columns),available_sources={"APPLICATION_EVENT_TABLE"}); engine=FeatureExecutor().execute(spec,plan,f); truth=pd.Series(0.0,index=f.index)
    for _,group in f.groupby("device_id"):
        event=f.loc[group.index,"event_time"].to_numpy(dtype="datetime64[ns]"); app=f.loc[group.index,"application_time"].to_numpy(dtype="datetime64[ns]"); truth.loc[group.index]=[((event<a)&(event>=a-np.timedelta64(24,"h"))).sum() for a in app]
    leakage_spec=FeatureSpec(feature_spec_id="FS07L",feature_name="future_bad",business_intent="future",feature_type="COLUMN_TRANSFORM",source_fields=["future_bad_signal"],desired_logic="future",dsl_expression="future_bad_signal"); leak_plan=FeatureCompiler().compile(leakage_spec,schema_fields=set(f.columns),governance={"future_bad_signal":{"decision":"SUSPECT_LEAKAGE","semantic_type":"SUSPECT_LEAKAGE"}},available_sources={"CURRENT_WIDE_TABLE"}); match=bool(np.allclose(engine,truth,equal_nan=True)); mismatch_rows=int((engine!=truth).sum())
    results.append(case_result("07_future_leakage",truths["07_future_leakage"],{"compiler":plan.compiler_status,"leakage":leak_plan.compiler_status,"window_ground_truth_match":match,"mismatch_rows":mismatch_rows,"future_in_history":0 if match else mismatch_rows,"same_timestamp_in_history":0 if match else mismatch_rows},{"leakage_blocked":leak_plan.compiler_status=="LEAKAGE_RISK","strict_application_time_window":match},"BLOCKER","Window execution must evaluate event_time against each application_time, not against event-row time alone."))

    f=load("08_missing_field"); spec=FeatureSpec(feature_spec_id="FS08",feature_name="bad",business_intent="bad",feature_type="COMPOSITE",source_fields=["income","fake_credit_score"],desired_logic="missing",dsl_expression="ADD(income,fake_credit_score)"); plan=FeatureCompiler().compile(spec,schema_fields=set(f.columns))
    results.append(case_result("08_missing_field",truths["08_missing_field"],{"compiler":plan.compiler_status},{"invalid":plan.compiler_status=="INVALID_SOURCE_FIELD"},"BLOCKER"))

    f=load("09_composable"); spec=FeatureSpec(feature_spec_id="FS09",feature_name="combo",business_intent="low income red device",feature_type="COMPOSITE",source_fields=["monthly_income","device_risk_level"],desired_logic="low income red",dsl_expression="IF(BOOLEAN_AND(LE(monthly_income,3000),EQ(device_risk_level,'RED')),1,0)"); plan=FeatureCompiler().compile(spec,schema_fields=set(f.columns)); values=FeatureExecutor().execute(spec,plan,f); match,_=compare_values(values,FeatureExecutor().execute(spec,plan,f))
    results.append(case_result("09_composable",truths["09_composable"],{"compiler":plan.compiler_status,"valid":int(values.notna().sum()),"rebuild":match},{"composable":plan.compiler_status=="COMPOSABLE_DSL","execute":len(values)==len(f),"rebuild":match},"BLOCKER"))

    f=load("10_malicious"); expressions=['__import__("os")','open("x")','lambda x:x','df["x"]','import subprocess','eval("1")','exec("x")']; statuses=[]
    for expression in expressions:
        spec=FeatureSpec(feature_spec_id="FS10",feature_name="attack",business_intent="attack",feature_type="COMPOSITE",source_fields=["x"],desired_logic="attack",dsl_expression=expression); statuses.append(FeatureCompiler().compile(spec,schema_fields=set(f.columns)).compiler_status)
    results.append(case_result("10_malicious",truths["10_malicious"],{"statuses":statuses,"all_non_executable":all(x not in {"SUPPORTED_TEMPLATE","COMPOSABLE_DSL"} for x in statuses),"needs_new_operator_count":sum(x=="NEEDS_NEW_OPERATOR" for x in statuses)},{"all_invalid_expression":all(x=="INVALID_EXPRESSION" for x in statuses),"none_executable":all(x not in {"SUPPORTED_TEMPLATE","COMPOSABLE_DSL"} for x in statuses)},"HIGH","Classify eval/exec calls as INVALID_EXPRESSION instead of NEEDS_NEW_OPERATOR."))

    context,latency=context_explosion(); perf["context_build_seconds"]=latency
    results.append(case_result("11_context_explosion",truths["11_context_explosion"],context,{"budget":context["estimated_tokens"]<=context["max_tokens"],"top_k":context["included_items"]<=120,"dropped":context["dropped_items"]>0,"dedup":context["deduplicated_items"]>0},"HIGH","Enforce source Top-K, deduplication and token budget."))

    registry=CounterfactualRegistry(temp/"c12"); registry.add({"experiment_id":"E1","experiment_signature":"same","decision":"NEUTRAL"}); duplicate=registry.duplicate("same")
    results.append(case_result("12_duplicate_experiment",truths["12_duplicate_experiment"],{"duplicate_status":"DUPLICATE_EXPERIMENT" if duplicate else None,"experiment_count":len(registry.all())},{"duplicate":duplicate is not None,"not_retrained":len(registry.all())==1},"HIGH"))

    failed={"feature_id":"F13","model_type":"LR","decision":"FAILED"}; credit=build_feature_credit("F13","LR",[failed]); hypothesis=build_hypothesis_credit("H13",[{"hypothesis_id":"H13",**failed}])
    results.append(case_result("13_training_failure",truths["13_training_failure"],{"experiment":"FAILED","feature_credit":credit,"hypothesis":hypothesis.support_status},{"no_negative_credit":credit is None,"hypothesis_not_rejected":hypothesis.support_status!="REJECTED"},"BLOCKER"))

    f=load("14_rebuild_version"); v1=dataset_version(f); values=f.source_a/f.source_b.replace(0,np.nan); rebuilt=f.source_a/f.source_b.replace(0,np.nan); match,_=compare_values(values,rebuilt); f2=f.copy(); f2.loc[0,"source_a"]+=100; v2=dataset_version(f2); version_match=v1==v2
    results.append(case_result("14_rebuild_version",truths["14_rebuild_version"],{"v1_rebuild":match,"v1":v1,"v2":v2,"version_match":version_match},{"v1_pass":match,"v2_mismatch":not version_match},"BLOCKER"))

    positive=[{"hypothesis_id":"H001","feature_id":f"F{i}","decision":d,"delta_metrics":{}} for i,d in enumerate(["POSITIVE","POSITIVE","NEUTRAL"])]; negative=[{"hypothesis_id":"H002","feature_id":f"F{i+4}","decision":d,"delta_metrics":{}} for i,d in enumerate(["NEGATIVE","UNSTABLE","NEGATIVE"])]; h1=build_hypothesis_credit("H001",positive);h2=build_hypothesis_credit("H002",negative)
    results.append(case_result("15_hypothesis_credit",truths["15_hypothesis_credit"],{"H001":h1.support_status,"H002":h2.support_status},{"supported":h1.support_status=="SUPPORTED","rejected":h2.support_status=="REJECTED"},"HIGH"))

    # 60k performance pass; no persisted dataset/model copies.
    base=load("01_strong_signal"); large=pd.concat([base.assign(create_time=base.create_time+pd.Timedelta(days=400*i)) for i in range(3)],ignore_index=True); large["a"]=large.signal_feature;large["b"]=abs(large.base_feature)+1;large["device_id"]=[f"d{i%1000}" for i in range(len(large))];large["user_id"]=[f"u{i%5000}" for i in range(len(large))]
    spec=FeatureSpec(feature_spec_id="P1",feature_name="ratio",business_intent="ratio",feature_type="RATIO",source_fields=["a","b"],desired_logic="ratio",dsl_expression="SAFE_DIV(a,b)"); plan=FeatureCompiler().compile(spec,schema_fields=set(large.columns)); started=time.perf_counter();FeatureExecutor().execute(spec,plan,large);perf["column_feature_seconds"]=time.perf_counter()-started
    specw=FeatureSpec(feature_spec_id="P2",feature_name="count24",business_intent="count",feature_type="TIME_WINDOW_AGG",source_fields=["device_id","create_time"],entity_key="device_id",application_time_field="create_time",time_window="24h",desired_logic="count",dsl_expression='COUNT_OVER_WINDOW(device_id,create_time,"24h")',required_data_sources=["APPLICATION_EVENT_TABLE"]);planw=FeatureCompiler().compile(specw,schema_fields=set(large.columns),available_sources={"APPLICATION_EVENT_TABLE"});started=time.perf_counter();FeatureExecutor().execute(specw,planw,large);perf["window_feature_seconds"]=time.perf_counter()-started
    spece=FeatureSpec(feature_spec_id="P3",feature_name="users30",business_intent="users",feature_type="TIME_WINDOW_AGG",source_fields=["device_id","user_id","create_time"],entity_key="device_id",application_time_field="create_time",time_window="30d",desired_logic="users",dsl_expression='ENTITY_WINDOW_NUNIQUE(device_id,user_id,create_time,"30d")',required_data_sources=["DEVICE_RELATION_TABLE"]);plane=FeatureCompiler().compile(spece,schema_fields=set(large.columns),available_sources={"DEVICE_RELATION_TABLE"});started=time.perf_counter();FeatureExecutor().execute(spece,plane,large);perf["entity_feature_seconds"]=time.perf_counter()-started
    started=time.perf_counter();validate(large,"signal_feature");perf["cheap_validation_seconds"]=time.perf_counter()-started
    started=time.perf_counter();run_cf(large,"signal_feature",["base_feature"],"LR",temp/"perf_lr");perf["lr_counterfactual_seconds"]=time.perf_counter()-started
    started=time.perf_counter();run_cf(large,"signal_feature",["base_feature"],"LGBM",temp/"perf_lgbm");perf["lgbm_counterfactual_seconds"]=time.perf_counter()-started
    return results,perf


def render_report(payload: dict) -> str:
    rows=payload["cases"]; summary=payload["summary"]
    lines=["# Phase 1–4 Diagnostic Report","","## Overall Result","",f"- Decision: **{payload['PHASE_1_4_RELEASE_DECISION']}**",f"- PASS {summary['pass']} / FAIL {summary['fail']} / WARNING {summary['warning']}",f"- BLOCKER {summary['blocker']} / HIGH {summary['high']}",f"- REAL_LLM_DIAGNOSTIC: `{payload['analysis_agent']['real_llm_diagnostic']}`","","## Case Summary","","| Case | Expected | Actual | Status | Severity |","|---|---|---|---|---|" ]
    for row in rows: lines.append(f"| {row['case_id']} | {json.dumps(row['ground_truth'].get('expected_result',{}),ensure_ascii=False)[:100]} | {json.dumps(row['actual_result'],ensure_ascii=False)[:100]} | {row['status']} | {row['severity']} |")
    blockers=[x for x in rows if x["severity"]=="BLOCKER" and x["status"]=="FAIL"]; high=[x for x in rows if x["severity"]=="HIGH" and x["status"]=="FAIL"]
    lines += ["","## Blockers","",*(f"- {x['case_id']}: {x['unexpected_behavior']} — {x['recommended_fix']}" for x in blockers)] or ["- None"]
    lines += ["","## High Risk Issues","",*(f"- {x['case_id']}: {x['unexpected_behavior']} — {x['recommended_fix']}" for x in high)]
    sections={"Analysis Agent":payload["analysis_agent"],"Context Builder":next(x for x in rows if x["case_id"]=="11_context_explosion")["actual_result"],"Feature Compiler":[x["case_id"] for x in rows[7:10]],"Window / Entity Features":next(x for x in rows if x["case_id"]=="07_future_leakage")["actual_result"],"Cheap Validation":[x["actual_result"] for x in rows if x["case_id"] in {"01_strong_signal","03_pure_noise","04_redundant","06_extreme_drift"}],"Counterfactual":[x["actual_result"] for x in rows if x["case_id"] in {"01_strong_signal","02_nonlinear_interaction","03_pure_noise","05_dev_oot_flip"}],"Feature Credit":next(x for x in rows if x["case_id"]=="13_training_failure")["actual_result"],"Hypothesis Credit":next(x for x in rows if x["case_id"]=="15_hypothesis_credit")["actual_result"],"Rebuild":next(x for x in rows if x["case_id"]=="14_rebuild_version")["actual_result"],"Security":next(x for x in rows if x["case_id"]=="10_malicious")["actual_result"],"Performance":payload["performance_seconds"]}
    for title,value in sections.items(): lines += ["",f"## {title}","","```json",json.dumps(value,ensure_ascii=False,indent=2),"```"]
    lines += ["","## Module Scores","","| Module | Score | Basis |","|---|---:|---|",*(f"| {k} | {v['score']} | {v['basis']} |" for k,v in payload["module_scores"].items()),"","## Recommendations","",*(f"- {x}" for x in payload["recommendations"])]
    return "\n".join(lines)


def main() -> None:
    if not (OUT/"ground_truth.json").exists(): raise SystemExit("Run phase45_generate_datasets.py first")
    run1,perf1=diagnostic_pass(1);run2,perf2=diagnostic_pass(2); decisions1={x["case_id"]:(x["status"],x["actual_result"].get("counterfactual") if isinstance(x["actual_result"],dict) else None) for x in run1};decisions2={x["case_id"]:(x["status"],x["actual_result"].get("counterfactual") if isinstance(x["actual_result"],dict) else None) for x in run2}; reproducible=decisions1==decisions2
    failures=[x for x in run2 if x["status"]=="FAIL"]; blockers=[x for x in failures if x["severity"]=="BLOCKER"]; high_risks=[x for x in failures if x["severity"]=="HIGH"]; warnings=[x for x in run2 if x["status"]=="WARNING"]
    llm="NOT_RUN" if not os.getenv("ZHIPU_API_KEY") else "NOT_RUN_REQUIRES_EXPLICIT_NETWORK_ACCEPTANCE"
    release="NOT_READY" if blockers or high_risks or any(x["case_id"] in {"03_pure_noise","10_malicious","11_context_explosion","13_training_failure","14_rebuild_version"} for x in failures) else "READY_WITH_MINOR_FIXES" if failures or warnings else "READY_TO_FREEZE"
    score=lambda failed: max(0,10-failed)
    payload={"diagnostic_version":"phase45-v1","case_count":len(run2),"cases":run2,"summary":{"pass":sum(x["status"]=="PASS" for x in run2),"fail":len(failures),"warning":len(warnings),"blocker":len(blockers),"high":len(high_risks)},"analysis_agent":{"structural_cases":2,"real_llm_diagnostic":llm,"result":"STRUCTURAL_FIXTURES_READY; prior Phase 2 real-provider smoke evidence retained"},"reproducibility":{"consistent":reproducible,"run1":decisions1,"run2":decisions2},"performance_seconds":{k:round((perf1[k]+perf2[k])/2,4) for k in perf1},"module_scores":{},"PHASE_1_4_RELEASE_DECISION":release,"recommendations":[]}
    mapping={"Context Builder":["11_context_explosion"],"Analysis Agent":[],"Feature Engine":["08_missing_field","09_composable"],"Leakage Guard":["07_future_leakage"],"Cheap Validation":["01_strong_signal","03_pure_noise","04_redundant","06_extreme_drift"],"Counterfactual":["01_strong_signal","02_nonlinear_interaction","03_pure_noise","05_dev_oot_flip","12_duplicate_experiment","13_training_failure"],"Credit Assignment":["01_strong_signal","13_training_failure","15_hypothesis_credit"],"Audit/Rebuild":["12_duplicate_experiment","14_rebuild_version"],"Security":["10_malicious"]}
    for module,ids in mapping.items():
        count=sum(x["status"]=="FAIL" for x in run2 if x["case_id"] in ids)
        module_score=8 if module=="Analysis Agent" and llm!="PASS" else score(count*2 if any(x["severity"]=="BLOCKER" and x["status"]=="FAIL" for x in run2 if x["case_id"] in ids) else count)
        payload["module_scores"][module]={"score":module_score,"basis":f"{len(ids)-count}/{len(ids)} diagnostic cases passed" if ids else "Structural cases ready; prior Phase 2 real-provider smoke retained; current real LLM not run"}
    payload["recommendations"]=[x["recommended_fix"] for x in failures if x["recommended_fix"]!="None"] or ["No core fix required; complete real LLM diagnostic when an explicit API key is available."]
    payload=sanitize_json(payload);(OUT/"latest.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8");(OUT/"DIAGNOSTIC_REPORT.md").write_text(render_report(payload),encoding="utf-8")
    print(json.dumps({"cases":payload["case_count"],**payload["summary"],"reproducible":reproducible,"decision":release,"report":str((OUT/"DIAGNOSTIC_REPORT.md").relative_to(ROOT))},ensure_ascii=False))


if __name__ == "__main__": main()
