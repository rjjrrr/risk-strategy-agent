from __future__ import annotations

import re
import uuid
from typing import Any
from .schemas import FeatureSpec


def _simple_case(expression: str) -> str | None:
    match=re.fullmatch(r"\s*CASE\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.+)\s+ELSE\s+([^ ]+)\s+END\s*",expression,flags=re.I)
    if not match:return None
    field,body,default=match.groups();pairs=re.findall(r"WHEN\s+('(?:[^']*)'|\"(?:[^\"]*)\"|[-\d.]+)\s+THEN\s+([-\d.]+)",body,flags=re.I)
    if not pairs:return None
    result=default
    for value,output in reversed(pairs):result=f"IF(EQ({field},{value}),{output},{result})"
    return result


def normalize_proposal(proposal: dict[str,Any], dataset_id: str, dataset_version: str | None = None) -> FeatureSpec:
    fields=[str(x) for x in proposal.get("source_fields",[])];kind=str(proposal.get("feature_type") or "UNKNOWN").upper();formula=str(proposal.get("dsl_expression") or proposal.get("formula") or "").strip()
    if not formula and kind in {"RATIO","SHORT_LONG_RATIO"} and len(fields)>=2:formula=f"SAFE_DIV({fields[0]},{fields[1]})"
    elif not formula and kind=="DIFFERENCE" and len(fields)>=2:formula=f"SUB({fields[0]},{fields[1]})"
    elif not formula and kind in {"RAW","COLUMN_TRANSFORM"} and fields:formula=fields[0]
    converted=_simple_case(formula)
    if converted:formula=converted
    formula=re.sub(r"\bAND\b","and",formula,flags=re.I)
    mapped={"RAW":"COLUMN_TRANSFORM","SHORT_LONG_RATIO":"RATIO","DERIVED_NUMERIC":"COMPOSITE","DERIVED_BINARY":"COMPOSITE"}.get(kind,kind)
    allowed={"COLUMN_TRANSFORM","RATIO","DIFFERENCE","MISSING_FLAG","TIME_WINDOW_AGG","ENTITY_AGG","CONDITIONAL_AGG","RULE_GROUP_DERIVED","COMPOSITE","UNKNOWN"}
    required=proposal.get("required_data_sources") or (["APPLICATION_EVENT_TABLE"] if mapped in {"TIME_WINDOW_AGG","CONDITIONAL_AGG"} else ["CURRENT_WIDE_TABLE"])
    return FeatureSpec(feature_spec_id=f"FS_{uuid.uuid4().hex[:12]}",feature_name=proposal.get("feature_name") or f"feature_{uuid.uuid4().hex[:6]}",business_intent=proposal.get("semantic_meaning") or proposal.get("business_intent") or "Feature proposal",feature_type=mapped if mapped in allowed else "UNKNOWN",source_fields=fields,source_feature_ids=proposal.get("source_feature_ids",[]),entity_key=proposal.get("entity_key"),application_time_field=proposal.get("application_time_field"),time_window=proposal.get("time_window"),desired_logic=proposal.get("desired_logic") or proposal.get("semantic_meaning") or formula,dsl_expression=formula or None,desired_operations=proposal.get("desired_operations",[]),required_data_sources=required,expected_direction=proposal.get("expected_direction"),hypothesis_id=proposal.get("hypothesis_id"),proposal_id=proposal.get("proposal_id"),semantic_domain=proposal.get("semantic_domain","LLM_PROPOSAL"),dataset_id=dataset_id,dataset_version=dataset_version)
