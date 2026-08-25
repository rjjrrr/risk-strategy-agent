from __future__ import annotations

from typing import Any, Protocol

from .state import RiskGraphState


class AnalysisAdapter(Protocol):
    def build_context(self,state:RiskGraphState)->dict[str,Any]:...
    def analyze(self,state:RiskGraphState)->dict[str,Any]:...
    def guard_proposals(self,state:RiskGraphState)->dict[str,Any]:...
    def review_proposals(self,state:RiskGraphState,approved:bool)->dict[str,Any]:...


class FeatureAdapter(Protocol):
    def compile_feature(self,state:RiskGraphState)->dict[str,Any]:...
    def execute_feature(self,state:RiskGraphState)->dict[str,Any]:...


class ValidationAdapter(Protocol):
    def validate_feature(self,state:RiskGraphState)->dict[str,Any]:...


class DecisionAdapter(Protocol):
    def build_decision_context(self,state:RiskGraphState)->dict[str,Any]:...
    def decide(self,state:RiskGraphState)->dict[str,Any]:...
    def plan_experiment(self,state:RiskGraphState)->dict[str,Any]:...
    def approve_action(self,state:RiskGraphState,approved:bool)->dict[str,Any]:...
    def next_decision(self,state:RiskGraphState)->dict[str,Any]:...


class ExperimentAdapter(Protocol):
    def execute_experiment(self,state:RiskGraphState)->dict[str,Any]:...
    def evaluate_counterfactual(self,state:RiskGraphState)->dict[str,Any]:...
    def rollback_business_state(self,state:RiskGraphState)->dict[str,Any]:...


class CreditAdapter(Protocol):
    def update_credit(self,state:RiskGraphState)->dict[str,Any]:...


class ShadowAdapter(Protocol):
    def predict_shadow(self,state:RiskGraphState)->dict[str,Any]:...
    def reconcile_shadow(self,state:RiskGraphState)->dict[str,Any]:...


class WorkflowAdapters:
    """Composable service boundary. Implementations call domain services; nodes never calculate business results."""
    def build_context(self,state):return {}
    def analyze(self,state):return {}
    def guard_proposals(self,state):return {}
    def review_proposals(self,state,approved):return {}
    def compile_feature(self,state):return {}
    def execute_feature(self,state):return {}
    def validate_feature(self,state):return {}
    def build_decision_context(self,state):return {}
    def decide(self,state):return {}
    def plan_experiment(self,state):return {}
    def approve_action(self,state,approved):return {}
    def execute_experiment(self,state):return {}
    def evaluate_counterfactual(self,state):return {}
    def update_credit(self,state):return {}
    def predict_shadow(self,state):return {}
    def reconcile_shadow(self,state):return {}
    def next_decision(self,state):return {"continue_workflow":False,"next_route":"end"}
    def rollback_business_state(self,state):return {"next_route":"end"}
