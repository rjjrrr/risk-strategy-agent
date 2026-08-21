from __future__ import annotations

from pathlib import Path
from core.model_agent.registry import JsonRegistry


class FeatureSpecRegistry(JsonRegistry):
    def __init__(self,root:str|Path):super().__init__(Path(root)/"feature_specs.json","feature_spec_id")
class ExecutionPlanRegistry(JsonRegistry):
    def __init__(self,root:str|Path):super().__init__(Path(root)/"feature_execution_plans.json","plan_id")
class FeatureExecutionRegistry(JsonRegistry):
    def __init__(self,root:str|Path):super().__init__(Path(root)/"feature_executions.json","execution_id")
class CapabilityGapRegistry(JsonRegistry):
    def __init__(self,root:str|Path):super().__init__(Path(root)/"feature_capability_gaps.json","gap_id")
