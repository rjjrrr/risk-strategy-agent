from __future__ import annotations

from pathlib import Path

from core.model_agent.registry import JsonRegistry


class DecisionRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "decision_registry.json", "decision_id")


class DecisionLoopRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "decision_loops.json", "loop_id")


class DecisionPlanRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "decision_plans.json", "plan_id")


class DecisionToolAuditRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "decision_tool_audit.json", "tool_call_id")


class DecisionApprovalRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "decision_approvals.json", "approval_id")
