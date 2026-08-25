from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from .registry import DecisionToolAuditRegistry
from .schemas import ToolCall, ToolExecution, utc_now


TOOL_ARGUMENTS = {
    "run_feature_validation": ({"dataset_id", "feature_id"}, {"dataset_id", "feature_id", "time_field"}),
    "run_lr_counterfactual": ({"dataset_id", "feature_id"}, {"dataset_id", "feature_id", "experiment_type", "seed"}),
    "run_lgbm_counterfactual": ({"dataset_id", "feature_id"}, {"dataset_id", "feature_id", "experiment_type", "seed"}),
    "run_feature_ablation": ({"dataset_id", "feature_id", "model_type"}, {"dataset_id", "feature_id", "model_type", "seed"}),
    "evaluate_model": ({"dataset_id"}, {"dataset_id", "state_id", "model_type"}),
    "get_model_state": ({"dataset_id"}, {"dataset_id"}),
    "rollback_state": ({"dataset_id"}, {"dataset_id", "state_id"}),
    "get_feature_credit": ({"dataset_id", "feature_id"}, {"dataset_id", "feature_id", "model_type"}),
    "get_hypothesis_credit": ({"dataset_id", "hypothesis_id"}, {"dataset_id", "hypothesis_id"}),
    "request_analysis_agent": ({"dataset_id", "reason"}, {"dataset_id", "reason", "focus_fields"}),
}


class ControlledToolRegistry:
    """Allowlisted Python tools only. No dynamic imports, functions, code, SQL, shell, or file operations."""

    def __init__(self, audit: DecisionToolAuditRegistry | None = None):
        self.handlers: dict[str, Callable[..., dict[str, Any]]] = {}
        self.audit = audit

    def register(self, name: str, handler: Callable[..., dict[str, Any]]) -> None:
        if name not in TOOL_ARGUMENTS:
            raise ValueError(f"Tool is not allowlisted: {name}")
        self.handlers[name] = handler

    @staticmethod
    def validate(call: ToolCall) -> None:
        required, allowed = TOOL_ARGUMENTS[call.tool_name]
        supplied = set(call.arguments)
        if missing := required - supplied:
            raise ValueError(f"Missing tool arguments: {sorted(missing)}")
        if unknown := supplied - allowed:
            raise ValueError(f"Unknown tool arguments: {sorted(unknown)}")
        forbidden_keys = {"code", "python", "shell", "sql", "path", "filename", "function", "command"}
        if supplied & forbidden_keys:
            raise ValueError("Executable or file-operation arguments are forbidden")

    def execute(self, call: ToolCall) -> ToolExecution:
        self.validate(call)
        call_id = f"TC_{uuid.uuid4().hex[:12]}"
        started = utc_now()
        try:
            if call.tool_name not in self.handlers:
                raise ValueError(f"Tool handler unavailable: {call.tool_name}")
            result = self.handlers[call.tool_name](**call.arguments)
            execution = ToolExecution(tool_call_id=call_id, tool_name=call.tool_name, arguments=call.arguments, status="SUCCESS", result=result or {}, started_at=started, finished_at=utc_now())
        except Exception as exc:
            execution = ToolExecution(tool_call_id=call_id, tool_name=call.tool_name, arguments=call.arguments, status="FAILED", error=f"{type(exc).__name__}: {exc}", started_at=started, finished_at=utc_now())
        if self.audit:
            self.audit.add(execution.model_dump())
        return execution
