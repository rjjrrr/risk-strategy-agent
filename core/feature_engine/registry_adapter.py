from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from core.model_agent.registry import FeatureRegistry
from .lineage import EXECUTION_CODE_VERSION, next_feature_version
from .schemas import FeatureExecutionPlan, FeatureSpec


class FeatureRegistryAdapter:
    def __init__(self,root:str|Path):self.registry=FeatureRegistry(root)

    def add_generated(self,spec:FeatureSpec,plan:FeatureExecutionPlan,*,artifact_path:str,execution_id:str)->dict[str,Any]:
        rows=self.registry.all();version=next_feature_version(rows,spec.feature_name);feature_id=f"F_GEN_{uuid.uuid4().hex[:10]}"
        row={"feature_id":feature_id,"feature_family_id":spec.feature_name,"feature_name":spec.feature_name,"feature_version":version,"version":version,"feature_type":spec.feature_type,"feature_spec_id":spec.feature_spec_id,"proposal_id":spec.proposal_id,"hypothesis_id":spec.hypothesis_id,"source_fields":spec.source_fields,"source_feature_ids":spec.source_feature_ids,"source_features":spec.source_feature_ids,"source_data_sources":spec.required_data_sources,"semantic_domain":spec.semantic_domain,"business_intent":spec.business_intent,"dsl_expression":spec.dsl_expression,"ast":plan.ast,"normalized_ast":plan.normalized_ast,"machine_formula":plan.machine_formula,"human_formula":plan.human_formula,"execution_plan_id":plan.plan_id,"execution_id":execution_id,"execution_code_version":EXECUTION_CODE_VERSION,"input_missing_policy":spec.input_missing_policy,"output_missing_policy":spec.output_missing_policy,"time_window":spec.time_window,"entity_key":spec.entity_key,"dataset_id":spec.dataset_id,"dataset_version":spec.dataset_version,"artifact_path":artifact_path,"status":"GENERATED","validation_result":{"validation_status":"NOT_RUN","cheap_validation_id":None},"lr_eligible":False,"lgbm_eligible":False,"approved":False}
        return self.registry.add(row)
