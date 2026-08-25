from __future__ import annotations

import time
from typing import Any, Callable

from langgraph.types import interrupt

from .exceptions import WorkflowError
from .state import NodeResult, RiskGraphState, assert_lightweight, utc_now


IDEMPOTENT_NODES={"feature_compile","feature_execute","cheap_validation","experiment_execute","counterfactual_evaluate","credit_update","shadow_reconcile"}


class WorkflowNodes:
    def __init__(self,adapters,registry):self.adapters=adapters;self.registry=registry

    @staticmethod
    def _refs(state):
        keys=("dataset_id","context_id","proposal_ids","feature_spec_ids","feature_ids","validation_ids","decision_loop_id","decision_id","plan_id","experiment_id","current_business_state_id")
        return {key:state.get(key) for key in keys if state.get(key) not in (None,[],{})}

    def _patch(self,state,node,fn:Callable[[],dict[str,Any]],*,cycle=None):
        run_id=state["run_id"]
        if self.registry.is_cancel_requested(run_id):return {"cancel_requested":True,"continue_workflow":False,"next_route":"end","current_node":node}
        cycle=int(state.get("decision_round") or 0) if cycle is None else cycle
        if node in IDEMPOTENT_NODES:
            cached=self.registry.successful_patch(run_id,node,cycle)
            if cached is not None:
                statuses={**state.get("node_status",{}),node:"SKIPPED"};result=NodeResult(node_name=node,status="SKIPPED",started_at=utc_now(),finished_at=utc_now(),input_refs=self._refs(state),output_refs=self._refs({**state,**cached}),warnings=["IDEMPOTENT_REUSE"]);return {**cached,"node_status":statuses,"current_node":node,"last_node_result":result.model_dump()}
        started=time.perf_counter();started_at=utc_now();node_run=self.registry.start_node(run_id,node,self._refs(state));statuses={**state.get("node_status",{}),node:"RUNNING"}
        try:
            patch=fn() or {};assert_lightweight(patch,"node_patch");result=NodeResult(node_name=node,status="SUCCESS",started_at=started_at,finished_at=utc_now(),input_refs=self._refs(state),output_refs=self._refs({**state,**patch}),warnings=list(patch.get("warnings") or []))
            patch={**patch,"current_node":node,"node_status":{**statuses,node:"SUCCESS"},"last_node_result":result.model_dump()}
            self.registry.finish_node(node_run,"SUCCESS",output_refs=self._refs({**state,**patch}),patch=patch,duration_ms=round((time.perf_counter()-started)*1000,3),reason_codes=[f"cycle:{cycle}"])
            return patch
        except Exception as exc:
            code=getattr(exc,"code",type(exc).__name__);target=getattr(exc,"route","rollback" if code in {"MODEL_TRAIN_FAILED","EXPERIMENT_FAILED","UNSTABLE"} else "review" if code=="LLM_FAILED" else "end")
            error={"node":node,"type":code,"summary":str(exc)[:300]};result=NodeResult(node_name=node,status="FAILED",started_at=started_at,finished_at=utc_now(),input_refs=self._refs(state),error=error);patch={"current_node":node,"node_status":{**statuses,node:"FAILED"},"errors":[*state.get("errors",[]),error],"next_route":target,"last_node_result":result.model_dump()}
            self.registry.finish_node(node_run,"FAILED",patch=patch,duration_ms=round((time.perf_counter()-started)*1000,3),error=error,reason_codes=[f"cycle:{cycle}",code]);return patch

    def entry_router(self,state):return self._patch(state,"entry_router",lambda:{"next_route":None},cycle=0)
    def build_context(self,state):return self._patch(state,"build_context",lambda:self.adapters.build_context(state),cycle=0)
    def analysis(self,state):return self._patch(state,"analysis",lambda:self.adapters.analyze(state),cycle=0)
    def proposal_guard(self,state):return self._patch(state,"proposal_guard",lambda:self.adapters.guard_proposals(state),cycle=0)

    def _review(self,state,node,review_type,on_decision,approved_route,rejected_route="end"):
        self.registry.waiting(state["run_id"],node,self._refs(state),review_type)
        answer=interrupt({"run_id":state["run_id"],"review_type":review_type,"node":node,"input_refs":self._refs(state),"question":"Approve this workflow action?"})
        approved=bool(answer.get("approved")) if isinstance(answer,dict) else bool(answer)
        self.registry.event(state["run_id"],"USER_APPROVED" if approved else "USER_REJECTED","SUCCESS",{"review_type":review_type})
        return self._patch(state,node,lambda:{**on_decision(approved),"approval_status":"APPROVED" if approved else "REJECTED","review_type":review_type,"next_route":approved_route if approved else rejected_route},cycle=0)

    def human_review_proposal(self,state):
        return self._review(state,"human_review_proposal","PROPOSAL_REVIEW",lambda approved:self.adapters.review_proposals(state,approved),"feature_compile")
    def feature_compile(self,state):return self._patch(state,"feature_compile",lambda:self.adapters.compile_feature(state),cycle=0)
    def feature_review(self,state):
        review=state.get("review_type") or "FEATURE_REVIEW";approved_route="decision_context" if state.get("validation_decision")=="REVIEW" else "feature_execute"
        if review=="LLM_FAILURE":approved_route="end"
        return self._review(state,"feature_review",review,lambda approved:{},approved_route)
    def feature_execute(self,state):return self._patch(state,"feature_execute",lambda:self.adapters.execute_feature(state),cycle=0)
    def cheap_validation(self,state):return self._patch(state,"cheap_validation",lambda:self.adapters.validate_feature(state),cycle=0)
    def decision_context(self,state):return self._patch(state,"decision_context",lambda:self.adapters.build_decision_context(state))
    def decision(self,state):return self._patch(state,"decision",lambda:self.adapters.decide(state))
    def experiment_plan(self,state):return self._patch(state,"experiment_plan",lambda:self.adapters.plan_experiment(state))
    def shadow_predict(self,state):return self._patch(state,"shadow_predict",lambda:self.adapters.predict_shadow(state))

    def approval_gate(self,state):
        if not state.get("requires_approval"):
            return self._patch(state,"approval_gate",lambda:{"approval_status":"NOT_REQUIRED","next_route":"experiment_execute"})
        review="MODEL_CHANGE_APPROVAL" if state.get("decision_action") in {"MODEL_SWITCH","MODEL_TUNE"} else "EXPERIMENT_APPROVAL"
        return self._review(state,"approval_gate",review,lambda approved:self.adapters.approve_action(state,approved),"experiment_execute","next_decision")

    def experiment_execute(self,state):return self._patch(state,"experiment_execute",lambda:self.adapters.execute_experiment(state))
    def counterfactual_evaluate(self,state):return self._patch(state,"counterfactual_evaluate",lambda:self.adapters.evaluate_counterfactual(state))
    def credit_update(self,state):return self._patch(state,"credit_update",lambda:self.adapters.update_credit(state))
    def shadow_reconcile(self,state):return self._patch(state,"shadow_reconcile",lambda:self.adapters.reconcile_shadow(state))
    def next_decision(self,state):return self._patch(state,"next_decision",lambda:self.adapters.next_decision(state))
    def rollback_node(self,state):return self._patch(state,"rollback_node",lambda:self.adapters.rollback_business_state(state))
