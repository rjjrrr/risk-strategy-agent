from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field
from core.decision_agent.schemas import DecisionOutput

ProviderType=Literal["OPENAI","DEEPSEEK","QWEN_OPENAI_COMPATIBLE","ZHIPU_OPENAI_COMPATIBLE","CUSTOM_OPENAI_COMPATIBLE","MOCK"]
AgentType=Literal["GENERAL_CHAT","ANALYSIS_AGENT","DECISION_AGENT"]

class LLMBindingInput(BaseModel):
    display_name:str; provider:ProviderType; base_url:str=""; key_ref:str|None=None; api_key:str|None=Field(default=None,exclude=True)
    model:str; temperature:float=.2; max_tokens:int=1200; timeout_seconds:float=30; enabled:bool=True; is_default:bool=False; priority:int=100; fallback_binding_id:str|None=None

class SemanticOutput(BaseModel):
    field:str; business_meaning:str; semantic_role:str; risk_domain:str; possible_relations:list[str]=[]; allowed_feature_ops:list[str]=[]; forbidden_feature_ops:list[str]=[]; confidence:Literal["HIGH","MEDIUM","LOW"]; reason:str

class HypothesisOutput(BaseModel):
    hypothesis:str; evidence:dict[str,Any]|list[Any]|str; evidence_types:list[str]=[]; risk_mechanism:str; candidate_feature_ideas:list[dict[str,Any]]=[]; expected_direction:str; confidence:Literal["HIGH","MEDIUM","LOW"]; cost:Literal["LOW","MEDIUM","HIGH"]

class PlannerOutput(BaseModel):
    next_action:str; selected_hypothesis:str|None=None; reason:str; expected_gain:str|None=None; confidence:Literal["HIGH","MEDIUM","LOW"]; cost:Literal["LOW","MEDIUM","HIGH"]; requires_human:bool=True

class DiagnosisOutput(BaseModel):
    diagnosis_type:str; evidence:dict[str,Any]|list[Any]|str; severity:str; confidence:Literal["HIGH","MEDIUM","LOW"]; recommended_action:str; rollback_target:str|None=None; requires_human:bool=True

class AnalysisFinding(BaseModel):
    title: str; finding_type: str; evidence: dict[str,Any]|list[Any]|str; interpretation: str
    confidence: Literal["HIGH","MEDIUM","LOW"]; source_ids: list[str] = Field(default_factory=list)

class AnalysisHypothesis(BaseModel):
    title: str; risk_mechanism: str; evidence: dict[str,Any]|list[Any]|str
    evidence_types: list[str] = Field(default_factory=list)
    source_fields: list[str] = Field(default_factory=list); expected_direction: str
    confidence: Literal["HIGH","MEDIUM","LOW"]; estimated_cost: Literal["LOW","MEDIUM","HIGH"]

class AnalysisFeatureProposal(BaseModel):
    feature_name: str; feature_type: str; source_fields: list[str] = Field(default_factory=list)
    formula: str; semantic_meaning: str; expected_direction: str; evidence: dict[str,Any]|list[Any]|str
    confidence: Literal["HIGH","MEDIUM","LOW"]
    status: Literal["READY_FOR_COMPILATION","NEEDS_FEATURE_ENGINE","INSUFFICIENT_DATA","LEAKAGE_RISK","REVIEW"]
    desired_operations: list[str] = Field(default_factory=list)
    required_data_sources: list[str] = Field(default_factory=list)
    entity_key: str | None = None
    time_window: str | None = None
    application_time_field: str | None = None
    feature_engine_requirements: dict[str,Any] = Field(default_factory=dict)

class AnalysisOutput(BaseModel):
    analysis_summary: str
    semantic_findings: list[AnalysisFinding] = Field(default_factory=list)
    hypotheses: list[AnalysisHypothesis] = Field(default_factory=list)
    feature_proposals: list[AnalysisFeatureProposal] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)

STRUCTURED_SCHEMAS={"ANALYSIS_AGENT":AnalysisOutput,"DECISION_AGENT":DecisionOutput,"SEMANTIC_ANALYSIS":SemanticOutput,"HYPOTHESIS":HypothesisOutput,"PLANNER":PlannerOutput,"DIAGNOSIS":DiagnosisOutput}
