from __future__ import annotations

import uuid
from typing import Any

from .ast import fields, normalized_ast, operators, parse_expression, windows
from .capability import FeatureCapabilityRegistry
from .exceptions import FeatureSpecInvalid
from .schemas import FeatureCapabilityGap, FeatureExecutionPlan, FeatureSpec

BLOCKED_GOVERNANCE={"TARGET_LEAKAGE","POST_LOAN_FEATURE","SUSPECT_LEAKAGE"}


def _gap(spec: FeatureSpec, *, operators_=None, sources=None, entities=None, missing_fields=None, reason: str, resolution: str) -> FeatureCapabilityGap:
    return FeatureCapabilityGap(gap_id=f"GAP_{uuid.uuid4().hex[:12]}",feature_spec_id=spec.feature_spec_id,missing_operator=operators_ or [],missing_data_source=sources or [],missing_entity_support=entities or [],missing_fields=missing_fields or [],reason=reason,suggested_resolution=resolution)


class FeatureCompiler:
    def __init__(self, capabilities: FeatureCapabilityRegistry | None = None):self.capabilities=capabilities or FeatureCapabilityRegistry()

    def compile(self,spec:FeatureSpec,*,schema_fields:set[str],governance:dict[str,dict[str,Any]]|None=None,available_sources:set[str]|None=None,feature_registry:list[dict[str,Any]]|None=None)->FeatureExecutionPlan:
        governance=governance or {};available_sources=available_sources or {"CURRENT_WIDE_TABLE"};feature_registry=feature_registry or []
        base=dict(plan_id=f"PLAN_{uuid.uuid4().hex[:12]}",feature_spec_id=spec.feature_spec_id,source_fields=spec.source_fields,source_features=spec.source_feature_ids,required_sources=spec.required_data_sources,dsl_expression=spec.dsl_expression,machine_formula=spec.dsl_expression,human_formula=spec.desired_logic,dataset_version=spec.dataset_version)
        missing_sources=sorted(set(spec.required_data_sources)-available_sources)
        if missing_sources:return FeatureExecutionPlan(**base,compiler_status="INSUFFICIENT_DATA",capability_gap=_gap(spec,sources=missing_sources,reason="Required data source is unavailable",resolution="Attach the named event/relation source before compilation."),warnings=[f"Missing data source: {x}" for x in missing_sources])
        missing=sorted(set(spec.source_fields)-schema_fields-{str(x.get('feature_name')) for x in feature_registry}-{str(x.get('feature_id')) for x in feature_registry})
        if missing:
            status="INSUFFICIENT_DATA" if spec.feature_type in {"TIME_WINDOW_AGG","ENTITY_AGG","CONDITIONAL_AGG"} or spec.entity_key in missing else "INVALID_SOURCE_FIELD"
            return FeatureExecutionPlan(**base,compiler_status=status,capability_gap=_gap(spec,missing_fields=missing,reason="Source fields are unavailable",resolution="Provide the missing fields or select a compatible dataset."),warnings=[f"Missing field: {x}" for x in missing])
        risky=[x for x in spec.source_fields if governance.get(x,{}).get("decision")=="SUSPECT_LEAKAGE" or governance.get(x,{}).get("semantic_type") in BLOCKED_GOVERNANCE]
        if risky:return FeatureExecutionPlan(**base,compiler_status="LEAKAGE_RISK",leakage_checks=[{"field":x,"status":"BLOCKED"} for x in risky],warnings=["Leakage-prone source fields are forbidden"])
        dates=[x for x in spec.source_fields if governance.get(x,{}).get("semantic_type")=="DATETIME"]
        if spec.entity_key and spec.entity_key not in schema_fields:return FeatureExecutionPlan(**base,compiler_status="UNSUPPORTED_ENTITY",capability_gap=_gap(spec,entities=[spec.entity_key],reason="Entity key is unavailable",resolution="Provide the required entity key."))
        if not self.capabilities.supports_window(spec.time_window):return FeatureExecutionPlan(**base,compiler_status="UNSUPPORTED_WINDOW",capability_gap=_gap(spec,reason=f"Unsupported window: {spec.time_window}",resolution=f"Use one of {sorted(self.capabilities.WINDOWS)}"))
        try:node=parse_expression(spec.dsl_expression or "")
        except FeatureSpecInvalid as exc:return FeatureExecutionPlan(**base,compiler_status="INVALID_EXPRESSION",warnings=[str(exc)])
        ast_fields=fields(node);unknown_fields=sorted(set(ast_fields)-schema_fields-{str(x.get('feature_name')) for x in feature_registry})
        if unknown_fields:return FeatureExecutionPlan(**base,compiler_status="INVALID_SOURCE_FIELD",ast=node.to_dict(),normalized_ast=normalized_ast(node),warnings=[f"AST field missing: {x}" for x in unknown_fields])
        ops=operators(node);unsupported=sorted(x for x in ops if not self.capabilities.supports(x))
        if unsupported:return FeatureExecutionPlan(**base,compiler_status="NEEDS_NEW_OPERATOR",operators=ops,ast=node.to_dict(),normalized_ast=normalized_ast(node),capability_gap=_gap(spec,operators_=unsupported,reason="DSL contains unsupported operators",resolution="Add and test deterministic operator implementations before execution."))
        safe_date_ops={"TIME_DIFF","DAYS_BETWEEN","HOURS_BETWEEN","HOUR","DAY_OF_WEEK","DAY_OF_MONTH","MONTH","IS_WEEKEND"}
        if dates and spec.feature_type=="COLUMN_TRANSFORM" and not set(ops)&safe_date_ops:
            return FeatureExecutionPlan(**base,compiler_status="DATETIME_RAW_FORBIDDEN",operators=ops,ast=node.to_dict(),normalized_ast=normalized_ast(node),leakage_checks=[{"field":x,"status":"DATETIME_RAW_BLOCKED"} for x in dates])
        bad_windows=sorted(x for x in windows(node) if not self.capabilities.supports_window(x))
        if bad_windows:return FeatureExecutionPlan(**base,compiler_status="UNSUPPORTED_WINDOW",operators=ops,ast=node.to_dict(),normalized_ast=normalized_ast(node),capability_gap=_gap(spec,reason=f"Unsupported windows: {bad_windows}",resolution=f"Use one of {sorted(self.capabilities.WINDOWS)}"))
        normalized=normalized_ast(node);meaning=spec.business_intent.strip().lower()
        for row in feature_registry:
            other=row.get("normalized_ast") or row.get("ast_normalized")
            same_sources=tuple(sorted(spec.source_fields))==tuple(sorted(str(x) for x in row.get("source_fields",[])))
            same_meaning=meaning==str(row.get("business_intent") or row.get("semantic_meaning") or row.get("calculation_description","")).strip().lower()
            if other==normalized and same_sources and same_meaning:return FeatureExecutionPlan(**base,compiler_status="DUPLICATE_FEATURE",operators=ops,ast=node.to_dict(),normalized_ast=normalized,existing_feature_id=row.get("feature_id"),warnings=["Equivalent normalized AST already exists"])
        template={"RATIO":"SAFE_DIV","DIFFERENCE":"SUB","MISSING_FLAG":"MISSING_FLAG"}.get(spec.feature_type)
        status="SUPPORTED_TEMPLATE" if template and ops==[template] else "SUPPORTED_TEMPLATE" if spec.feature_type=="COLUMN_TRANSFORM" and not ops else "COMPOSABLE_DSL"
        cost="HIGH" if len([x for x in ops if x in self.capabilities.TEMPORAL|self.capabilities.ENTITY])>1 else "MEDIUM" if any(x in self.capabilities.TEMPORAL|self.capabilities.ENTITY for x in ops) else "LOW"
        steps=[{"step":i+1,"operator":op,"executor":"WINDOW" if op in self.capabilities.TEMPORAL else "ENTITY" if op in self.capabilities.ENTITY else "DERIVED" if op in self.capabilities.DERIVED else "COLUMN"} for i,op in enumerate(ops)]
        return FeatureExecutionPlan(**base,compiler_status=status,operators=ops,execution_steps=steps,ast=node.to_dict(),normalized_ast=normalized,estimated_cost=cost,leakage_checks=[{"field":x,"status":"PASS"} for x in spec.source_fields])
