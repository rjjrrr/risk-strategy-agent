from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable

from .context import build_decision_context
from .engine import DecisionEngine
from .registry import DecisionApprovalRegistry, DecisionLoopRegistry, DecisionPlanRegistry, DecisionRegistry
from .schemas import DecisionBudget, DecisionLoopState, DecisionOutput, ToolCall, utc_now
from .tools import ControlledToolRegistry


EXPERIMENT_ACTIONS = {"TEST_FEATURE", "TEST_HYPOTHESIS", "REMOVE_FEATURE_ABLATION", "MODEL_SWITCH", "MODEL_TUNE"}


class DecisionLoopManager:
    """One explicit round/action at a time; never runs an unbounded autonomous loop."""

    def __init__(
        self,
        root: str | Path,
        dataset_id: str,
        tools: ControlledToolRegistry,
        *,
        context_provider: Callable[[str], dict[str, Any]],
        state_provider: Callable[[str], dict[str, Any]],
        llm_decider: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        shadow_observer: Callable[[dict[str, Any], str], Any] | None = None,
        shadow_reconciler: Callable[[str, dict[str, Any], str | None], Any] | None = None,
    ):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.dataset_id = dataset_id; self.tools = tools
        self.context_provider = context_provider; self.state_provider = state_provider; self.llm_decider = llm_decider
        self.shadow_observer=shadow_observer;self.shadow_reconciler=shadow_reconciler
        self.engine = DecisionEngine()
        self.loops = DecisionLoopRegistry(self.root); self.decisions = DecisionRegistry(self.root)
        self.plans = DecisionPlanRegistry(self.root); self.approvals = DecisionApprovalRegistry(self.root)

    def create(self, budget: DecisionBudget | None = None) -> dict[str, Any]:
        model_state = self.state_provider(self.dataset_id) or {}
        selected_budget = budget or DecisionBudget()
        state = DecisionLoopState(
            loop_id=f"DL_{uuid.uuid4().hex[:12]}", dataset_id=self.dataset_id,
            current_state_id=model_state.get("current_state_id"), best_state_id=model_state.get("best_state_id"),
            last_stable_state_id=model_state.get("last_stable_state_id"),
            active_hypotheses=list(model_state.get("active_hypotheses") or []),
            budget=selected_budget, budget_remaining=selected_budget.remaining,
        )
        return self.loops.add(state.model_dump())

    def get(self, loop_id: str) -> dict[str, Any]:
        state = self.loops.get(loop_id)
        if not state:
            raise KeyError(loop_id)
        return state

    def _save(self, state: dict[str, Any], **changes) -> dict[str, Any]:
        changes["updated_at"] = utc_now()
        return self.loops.update(state["loop_id"], **changes)

    def diagnose(self, loop_id: str, *, use_llm: bool = False) -> dict[str, Any]:
        state = self.get(loop_id)
        budget = DecisionBudget.model_validate(state["budget"])
        if budget.remaining <= 0:
            return self._save(state, status="BUDGET_EXHAUSTED", budget_remaining=0, stop_reason="EXPERIMENT_BUDGET_EXHAUSTED")
        if state["round"] >= budget.max_rounds:
            return self._save(state, status="STOPPED", stop_reason="MAX_ROUNDS_REACHED")

        bounded = build_decision_context(self.context_provider(self.dataset_id))
        trace = None
        if use_llm:
            try:
                if self.llm_decider is None:
                    raise RuntimeError("LLM decision provider is unavailable")
                response = self.llm_decider(bounded)
                trace = response.get("trace") or {}
                if trace.get("runtime_type") != "LLM":
                    raise RuntimeError("Decision execution requires a real LLM runtime")
                decision = DecisionOutput.model_validate(response.get("decision"))
            except Exception as exc:
                return self._save(state, status="STOPPED", stop_reason=f"LLM_FAILED:{type(exc).__name__}")
        else:
            decision = self.engine.diagnose(
                bounded["context"], blocked_features=state.get("blocked_feature_ids"),
                tested_actions=state.get("tested_actions"),
            )

        decision_id = f"DEC_{uuid.uuid4().hex[:12]}"
        selected = decision.selected_action
        blocked = list(state.get("blocked_feature_ids") or [])
        if decision.diagnosis == "LEAKAGE" and selected:
            blocked = sorted(set(blocked + selected.feature_ids))
        record = {
            "decision_id": decision_id, "loop_id": loop_id, **decision.model_dump(),
            "result": {"llm_trace": trace} if trace else {}, "reason": selected.reason if selected else decision.stop_reason or "No action",
            "context_hash": bounded["context_hash"], "model_state_before": state.get("current_state_id"),
            "model_state_after": state.get("current_state_id"), "experiment_id": None,
        }
        self.decisions.add(record)
        if self.shadow_observer:
            try:self.shadow_observer(record,bounded["context_hash"])
            except Exception:pass  # Shadow telemetry must never block Phase5.
        plan = self.engine.compile_plan(decision_id, decision, baseline_state_id=state.get("current_state_id"))
        self.plans.add(plan.model_dump())
        history = list(state.get("diagnosis_history") or []) + [{"decision_id": decision_id, "diagnosis": decision.diagnosis, "evidence": [row.model_dump() for row in decision.evidence], "round": state["round"] + 1}]
        status = "WAITING_APPROVAL" if plan.human_approval_required else "RUNNING"
        approval_id = None
        if plan.human_approval_required:
            approval_id = f"DA_{uuid.uuid4().hex[:12]}"
            self.approvals.add({"approval_id": approval_id, "loop_id": loop_id, "plan_id": plan.plan_id, "action_type": plan.action_type, "reason": selected.reason if selected else "", "status": "PENDING", "decided_by": None})
        return self._save(
            state, round=state["round"] + 1, status=status,
            latest_decision_id=decision_id, latest_plan_id=plan.plan_id,
            pending_approval_id=approval_id, diagnosis_history=history,
            blocked_feature_ids=blocked, stop_reason=decision.stop_reason,
        )

    def _tool_call(self, plan: dict[str, Any]) -> ToolCall | None:
        if not plan.get("required_tools"):
            return None
        name = plan["required_tools"][0]
        args: dict[str, Any] = {"dataset_id": self.dataset_id}
        if plan.get("feature_ids"):
            args["feature_id"] = plan["feature_ids"][0]
        if name in {"run_lr_counterfactual", "run_lgbm_counterfactual"}:
            args.update(experiment_type="FEATURE_ADD", seed=42)
        elif name == "run_feature_ablation":
            args.update(model_type=plan.get("model_type") or "LR", seed=42)
        elif name == "evaluate_model":
            args.update(model_type=plan.get("model_type"), state_id=plan.get("baseline_state_id"))
        elif name == "rollback_state":
            args["state_id"] = plan.get("baseline_state_id")
        elif name == "request_analysis_agent":
            args.update(reason=plan.get("expected_change"), focus_fields=plan.get("feature_ids") or [])
        return ToolCall(tool_name=name, arguments=args)

    @staticmethod
    def _outcome(plan: dict[str, Any], result: dict[str, Any]) -> str:
        decision = result.get("decision") or result.get("counterfactual_decision") or result.get("outcome")
        if decision in {"FAILED", "NEGATIVE", "UNSTABLE", "ROLLBACK"}:
            return "ROLLBACK" if decision in {"FAILED", "UNSTABLE", "ROLLBACK"} else "REJECT"
        if plan["action_type"] == "REMOVE_FEATURE_ABLATION" and decision in {"NEUTRAL", "ACCEPT_SIMPLIFICATION"}:
            return "ACCEPT_SIMPLIFICATION"
        if decision in {"POSITIVE", "ACCEPT_PERFORMANCE"}:
            return "ACCEPT_PERFORMANCE"
        if decision in {"REVIEW"}:
            return "REVIEW"
        return "INCONCLUSIVE"

    def execute(self, loop_id: str) -> dict[str, Any]:
        state = self.get(loop_id)
        if state["status"] == "WAITING_APPROVAL":
            raise ValueError("HUMAN_APPROVAL_REQUIRED")
        if state["status"] not in {"RUNNING"}:
            raise ValueError(f"Loop cannot execute from status {state['status']}")
        plan = self.plans.get(state.get("latest_plan_id"))
        if not plan:
            raise ValueError("No selected experiment plan")
        if plan["action_type"] in {"STOP_EXPLORATION", "NO_ACTION"}:
            return self._save(state, status="SUCCESS", stop_reason=state.get("stop_reason") or plan["action_type"])
        call = self._tool_call(plan)
        if call is None:
            return self._save(state, status="WAITING_APPROVAL", stop_reason="ACTION_HAS_NO_AUTO_TOOL")

        execution = self.tools.execute(call)
        result = execution.result if execution.status == "SUCCESS" else {"decision": "FAILED", "error": execution.error}
        outcome = self._outcome(plan, result)
        experiment_id = result.get("experiment_id")
        model_after = self.state_provider(self.dataset_id) or {}
        decision_record = self.decisions.get(state.get("latest_decision_id")) or {}
        selected_prediction = (decision_record.get("selected_action") or {}).get("surrogate_prediction") or {}
        tested = list(state.get("tested_actions") or []) + [{
            "round": state["round"], "plan_id": plan["plan_id"], "action_type": plan["action_type"],
            "feature_ids": plan.get("feature_ids", []), "model_type": plan.get("model_type"),
            "tool_call_id": execution.tool_call_id, "experiment_id": experiment_id,
            "outcome": outcome, "result": result, "prediction": selected_prediction,
            "actual_delta_metrics": result.get("delta_metrics") or {},
        }]
        no_gain = state.get("consecutive_no_gain", 0) + 1 if outcome in {"REJECT", "INCONCLUSIVE"} else 0
        budget = DecisionBudget.model_validate(state["budget"])
        if plan["action_type"] in EXPERIMENT_ACTIONS:
            budget.experiments_used += 1; budget.experiments_this_round += 1

        status = "RUNNING"
        stop_reason = None
        approval_id = None
        if execution.status == "FAILED" or outcome == "ROLLBACK":
            rollback = self.tools.execute(ToolCall(tool_name="rollback_state", arguments={"dataset_id": self.dataset_id, "state_id": state.get("last_stable_state_id")}))
            result["rollback"] = rollback.model_dump()
            status, stop_reason = "ROLLBACK", "EXPERIMENT_FAILED_OR_UNSTABLE"
        elif outcome == "ACCEPT_SIMPLIFICATION":
            approval_id = f"DA_{uuid.uuid4().hex[:12]}"
            self.approvals.add({"approval_id": approval_id, "loop_id": loop_id, "plan_id": plan["plan_id"], "action_type": "PERMANENT_FEATURE_REMOVE", "reason": "Ablation accepted simplification; permanent removal remains human-gated", "status": "PENDING", "decided_by": None})
            status, stop_reason = "WAITING_APPROVAL", "PERMANENT_FEATURE_REMOVE_REQUIRES_APPROVAL"
        elif no_gain >= 2:
            status, stop_reason = "STOPPED", "TWO_EXPERIMENTS_WITHOUT_MATERIAL_GAIN"
        elif budget.remaining <= 0:
            status, stop_reason = "BUDGET_EXHAUSTED", "EXPERIMENT_BUDGET_EXHAUSTED"

        self.decisions.update(
            state["latest_decision_id"], result={"tool_execution": execution.model_dump(), "outcome": outcome, "feature_credit": result.get("feature_credit"), "hypothesis_credit": result.get("hypothesis_credit")},
            model_state_after=model_after.get("current_state_id"), experiment_id=experiment_id,
        )
        if self.shadow_reconciler:
            try:self.shadow_reconciler(state["latest_decision_id"],result,model_after.get("current_state_id"))
            except Exception:pass
        return self._save(
            state, status=status, tested_actions=tested, budget=budget.model_dump(), budget_remaining=budget.remaining,
            latest_experiment_id=experiment_id, current_state_id=model_after.get("current_state_id", state.get("current_state_id")),
            best_state_id=model_after.get("best_state_id", state.get("best_state_id")),
            last_stable_state_id=model_after.get("last_stable_state_id", state.get("last_stable_state_id")),
            consecutive_no_gain=no_gain, pending_approval_id=approval_id, stop_reason=stop_reason,
        )

    def approve(self, loop_id: str, approved_by: str = "HUMAN") -> dict[str, Any]:
        state = self.get(loop_id); approval_id = state.get("pending_approval_id")
        if not approval_id:
            raise ValueError("No pending approval")
        self.approvals.update(approval_id, status="APPROVED", decided_by=approved_by, decided_at=utc_now())
        if state.get("latest_decision_id"):
            self.decisions.update(state["latest_decision_id"], approved_by=approved_by)
        plan = self.plans.get(state.get("latest_plan_id")) or {}
        status = "SUCCESS" if (self.approvals.get(approval_id) or {}).get("action_type") == "PERMANENT_FEATURE_REMOVE" else "RUNNING"
        return self._save(state, status=status, pending_approval_id=None, stop_reason="PERMANENT_REMOVAL_APPROVED" if status == "SUCCESS" else None)

    def reject(self, loop_id: str, rejected_by: str = "HUMAN") -> dict[str, Any]:
        state = self.get(loop_id); approval_id = state.get("pending_approval_id")
        if not approval_id:
            raise ValueError("No pending approval")
        approval = self.approvals.update(approval_id, status="REJECTED", decided_by=rejected_by, decided_at=utc_now())
        rejected = list(state.get("rejected_actions") or []) + [{"plan_id": approval.get("plan_id"), "action_type": approval.get("action_type"), "reason": "HUMAN_REJECTED"}]
        return self._save(state, status="STOPPED", pending_approval_id=None, rejected_actions=rejected, stop_reason="HUMAN_REJECTED")

    def rollback(self, loop_id: str) -> dict[str, Any]:
        state = self.get(loop_id)
        execution = self.tools.execute(ToolCall(tool_name="rollback_state", arguments={"dataset_id": self.dataset_id, "state_id": state.get("last_stable_state_id")}))
        if execution.status != "SUCCESS":
            return self._save(state, status="FAILED", stop_reason="ROLLBACK_FAILED")
        model = self.state_provider(self.dataset_id) or {}
        return self._save(state, status="ROLLBACK", current_state_id=model.get("current_state_id", state.get("last_stable_state_id")), stop_reason="MANUAL_ROLLBACK")

    def stop(self, loop_id: str, reason: str = "HUMAN_STOP") -> dict[str, Any]:
        return self._save(self.get(loop_id), status="STOPPED", stop_reason=reason)

    def feedback_context(self, loop_id: str) -> dict[str, Any]:
        state = self.get(loop_id)
        decision = self.decisions.get(state.get("latest_decision_id")) if state.get("latest_decision_id") else None
        return {
            "loop_id": loop_id, "round": state["round"], "status": state["status"],
            "previous_action": decision.get("selected_action") if decision else None,
            "experiment_id": state.get("latest_experiment_id"),
            "experiment_result": (decision or {}).get("result", {}),
            "state_change": {"current": state.get("current_state_id"), "best": state.get("best_state_id"), "last_stable": state.get("last_stable_state_id")},
            "budget_remaining": state.get("budget_remaining"), "stop_reason": state.get("stop_reason"),
        }
