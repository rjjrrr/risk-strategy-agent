from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

SourceType = Literal[
    "DATASET_SUMMARY", "DATA_HEALTH", "GOVERNANCE", "VARIABLE_PROFILE",
    "RULE_SUMMARY", "RULE_GROUP", "FEATURE_REGISTRY", "HYPOTHESIS_REGISTRY",
    "EXPERIMENT_HISTORY", "MODEL_STATE", "CONVERSATION_MEMORY", "FEATURE_ENGINE_CAPABILITIES",
]
Priority = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


class ContextRequest(BaseModel):
    conversation_id: str
    dataset_id: str
    user_query: str = ""
    agent_type: str = "ANALYSIS_AGENT"
    focus_fields: list[str] = Field(default_factory=list)
    include_dataset_summary: bool = True
    include_data_health: bool = True
    include_governance: bool = True
    include_variable_profiles: bool = True
    include_rules: bool = True
    include_rule_groups: bool = True
    include_features: bool = True
    include_hypotheses: bool = True
    include_experiments: bool = True
    include_model_state: bool = True
    include_conversation_memory: bool = True
    include_feature_engine_capabilities: bool = True
    max_context_tokens: int = Field(default=8000, ge=500, le=12000)
    max_items_per_source: int = Field(default=20, ge=1, le=100)


class ContextItem(BaseModel):
    source_type: SourceType
    source_id: str
    title: str
    content: dict[str, Any]
    priority: Priority = "MEDIUM"
    relevance_score: float = 0.0
    created_at: str | None = None
    version: str = "1"
    tags: list[str] = Field(default_factory=list)
    field_names: list[str] = Field(default_factory=list)


class ContextBundle(BaseModel):
    context_id: str
    request: ContextRequest
    items: list[ContextItem]
    text: str
    context_hash: str
    included_items: int
    dropped_items: int
    deduplicated_items: int
    estimated_context_tokens: int
    sources_used: list[str]
    source_counts: dict[str, int]
    versions: dict[str, str]
    cache_hit: bool = False
    created_at: str
