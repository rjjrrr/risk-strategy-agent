from __future__ import annotations

from core.context import ContextRequest
from core.counterfactual.audit import CounterfactualRegistry
from core.decision_agent.schemas import DecisionBudget
from core.feature_validation.audit import FeatureValidationRegistry
from core.model_agent.registry import FeatureRegistry
from core.workflow.adapters import WorkflowAdapters
from core.workflow.exceptions import FeatureWorkflowError, LLMWorkflowError, ModelWorkflowError

from .. import config
from . import agent_chat_service, context_service, decision_agent_service, experiment_memory_service, feature_engine_service, feature_validation_service, shadow_service


class ServiceWorkflowAdapters(WorkflowAdapters):
    """Thin adapters only; all calculations stay in the existing services."""
    def _root(self,state):return config.MODEL_AGENT_DIR/state["dataset_id"]

    def build_context(self,state):
        conversation_id=state.get("conversation_id")
        if not conversation_id:
            conversation_id=agent_chat_service.store.create_conversation(title=f"Workflow {state['run_id']}",agent_type="ANALYSIS_AGENT",dataset_id=state["dataset_id"])["conversation_id"]
        bundle=context_service.build(ContextRequest(conversation_id=conversation_id,dataset_id=state["dataset_id"],user_query="Find evidence-backed risk feature proposals for the controlled workflow.",agent_type="ANALYSIS_AGENT"),agent_chat_service.store)
        return {"conversation_id":conversation_id,"context_id":bundle.context_id,"context_hash":bundle.context_hash,"next_route":"analysis","summaries":{**state.get("summaries",{}),"context":{"items":bundle.included_items,"tokens":bundle.estimated_context_tokens}}}

    def analyze(self,state):
        if state.get("proposal_ids"):return {"next_route":"proposal_guard"}
        try:result=agent_chat_service.send(state["conversation_id"],"Analyze the current risk evidence and propose safe hypotheses and features.",agent_type="ANALYSIS_AGENT")
        except Exception as exc:raise LLMWorkflowError(str(exc)) from exc
        if result.get("trace",{}).get("runtime_type")!="LLM":raise LLMWorkflowError("REAL_LLM_REQUIRED; mock output cannot continue the workflow")
        proposal_ids=[x["proposal_id"] for x in result.get("proposals",[])];hypotheses=[x["proposal_id"] for x in result.get("proposals",[]) if x.get("proposal_type")=="HYPOTHESIS_CREATE"]
        return {"proposal_ids":proposal_ids,"hypothesis_ids":hypotheses,"next_route":"proposal_guard" if proposal_ids else "end","warnings":state.get("warnings",[])+([] if proposal_ids else ["REQUEST_MORE_DATA:NO_PROPOSAL"])}

    def guard_proposals(self,state):
        rows=[agent_chat_service.store.proposal(x) for x in state.get("proposal_ids",[])];codes=[(x.get("payload",{}).get("validation") or {}).get("validation_code") for x in rows]
        if any(x in {"INVALID_SOURCE_FIELD","LEAKAGE_RISK"} for x in codes):return {"next_route":"end","review_type":"PROPOSAL_REVIEW","warnings":state.get("warnings",[])+[f"PROPOSAL_BLOCKED:{','.join(str(x) for x in codes if x)}"]}
        if any(x and x.startswith("DUPLICATE") for x in codes):return {"next_route":"review","review_type":"PROPOSAL_REVIEW"}
        return {"next_route":"human_review_proposal","review_type":"PROPOSAL_REVIEW"}

    def review_proposals(self,state,approved):
        if not approved:return {"next_route":"end"}
        features=list(state.get("feature_ids",[]));hypotheses=[]
        for proposal_id in state.get("proposal_ids",[]):
            proposal=agent_chat_service.store.proposal(proposal_id)
            if proposal.get("status")=="PENDING":proposal=agent_chat_service.decide_proposal(proposal_id,True)
            object_id=proposal.get("registry_object_id")
            if object_id:
                (features if proposal.get("proposal_type")=="FEATURE_CANDIDATE" else hypotheses).append(object_id)
        return {"feature_ids":features,"hypothesis_ids":hypotheses,"next_route":"feature_compile"}

    def compile_feature(self,state):
        proposals=[agent_chat_service.store.proposal(x) for x in state.get("proposal_ids",[])];feature_proposal=next((x for x in proposals if x.get("proposal_type")=="FEATURE_CANDIDATE"),None)
        if not feature_proposal:
            if state.get("feature_ids"):return {"next_route":"cheap_validation"}
            raise FeatureWorkflowError("No approved feature proposal")
        existing=next((x for x in feature_engine_service.feature_specs(state["dataset_id"]) if x.get("proposal_id")==feature_proposal["proposal_id"]),None)
        spec=existing or feature_engine_service.spec_from_proposal(state["dataset_id"],feature_proposal["proposal_id"])
        plan=feature_engine_service.compile_spec(state["dataset_id"],spec["feature_spec_id"]);status=plan.get("compiler_status")
        route="feature_execute" if status in {"SUPPORTED_TEMPLATE","COMPOSABLE_DSL"} else "review" if status in {"NEEDS_NEW_OPERATOR","REVIEW_REQUIRED","DUPLICATE_FEATURE"} else "end"
        return {"feature_spec_ids":[spec["feature_spec_id"]],"plan_id":plan["plan_id"],"next_route":route,"review_type":"FEATURE_REVIEW" if route=="review" else None,"summaries":{**state.get("summaries",{}),"compiler_status":status}}

    def execute_feature(self,state):
        plan_id=state.get("plan_id");prior=next((x for x in feature_engine_service.executions(state["dataset_id"]) if x.get("plan_id")==plan_id and x.get("status")=="SUCCESS"),None)
        try:result=prior or feature_engine_service.execute_plan(state["dataset_id"],plan_id,user_confirmed=True)
        except Exception as exc:raise FeatureWorkflowError(str(exc)) from exc
        if result.get("status")!="SUCCESS":raise FeatureWorkflowError(result.get("error_summary") or "Feature execution failed")
        feature_id=result.get("feature_id") or result.get("feature",{}).get("feature_id")
        return {"feature_ids":[feature_id],"next_route":"cheap_validation","summaries":{**state.get("summaries",{}),"feature_execution_id":result.get("execution_id")}}

    def validate_feature(self,state):
        feature_id=state.get("feature_ids",[])[0];prior=FeatureValidationRegistry(self._root(state)).latest_for_feature(feature_id);result=prior or feature_validation_service.run_validation(state["dataset_id"],feature_id)
        decision=result.get("decision");route="decision_context" if decision in {"PROMISING","EXPLORATORY"} else "review" if decision=="REVIEW" else "credit_update" if decision=="REJECTED" else "end"
        return {"validation_ids":[result["validation_id"]],"validation_decision":decision,"next_route":route,"review_type":"FEATURE_REVIEW" if route=="review" else None}

    def build_decision_context(self,state):
        loop=decision_agent_service.manager(state["dataset_id"]).get(state["decision_loop_id"]) if state.get("decision_loop_id") else decision_agent_service.create_loop(state["dataset_id"],DecisionBudget(max_rounds=3,max_total_experiments=6).model_dump())
        return {"decision_loop_id":loop["loop_id"],"decision_round":int(loop.get("round") or 0),"budget_remaining":int(loop.get("budget_remaining") or 0),"current_business_state_id":loop.get("current_state_id"),"best_business_state_id":loop.get("best_state_id"),"last_stable_state_id":loop.get("last_stable_state_id"),"next_route":"decision"}

    def decide(self,state):
        manager=decision_agent_service.manager(state["dataset_id"]);loop=manager.get(state["decision_loop_id"])
        if int(loop.get("budget_remaining") or 0)<=0:return {"continue_workflow":False,"next_route":"end","warnings":state.get("warnings",[])+["BUDGET_EXHAUSTED"]}
        loop=manager.diagnose(loop["loop_id"],use_llm=False);record=manager.decisions.get(loop.get("latest_decision_id")) or {};selected=record.get("selected_action") or {};action=selected.get("action_type")
        route="experiment_plan" if action in {"TEST_FEATURE","TEST_HYPOTHESIS","REMOVE_FEATURE_ABLATION","MODEL_SWITCH","MODEL_TUNE"} else "rollback" if action=="ROLLBACK" else "end"
        return {"decision_id":record.get("decision_id"),"plan_id":loop.get("latest_plan_id"),"decision_action":action,"decision_round":int(loop.get("round") or 0),"budget_remaining":int(loop.get("budget_remaining") or 0),"requires_approval":bool(record.get("requires_human_approval")),"next_route":route,"summaries":{**state.get("summaries",{}),"final_selection_policy":"PHASE5"}}

    def plan_experiment(self,state):
        plan=decision_agent_service.manager(state["dataset_id"]).plans.get(state["plan_id"])
        return {"requires_approval":bool(plan.get("human_approval_required")),"next_route":"shadow_predict","summaries":{**state.get("summaries",{}),"plan":{"action_type":plan.get("action_type"),"risk":plan.get("risk"),"cost":plan.get("cost")}}}

    def predict_shadow(self,state):
        rows=[x for x in shadow_service.predictions(state["dataset_id"],1000) if x.get("decision_id")==state.get("decision_id")]
        return {"shadow_prediction_ids":[x["shadow_id"] for x in rows],"next_route":"approval_gate","summaries":{**state.get("summaries",{}),"shadow_only":True,"final_selection_policy":"PHASE5"}}

    def approve_action(self,state,approved):
        manager=decision_agent_service.manager(state["dataset_id"]);loop=manager.get(state["decision_loop_id"])
        if loop.get("pending_approval_id"):manager.approve(loop["loop_id"],"WORKFLOW_USER") if approved else manager.reject(loop["loop_id"],"WORKFLOW_USER")
        return {"next_route":"experiment_execute" if approved else "next_decision"}

    def execute_experiment(self,state):
        manager=decision_agent_service.manager(state["dataset_id"]);loop=manager.get(state["decision_loop_id"])
        registry=CounterfactualRegistry(self._root(state));interrupted=[x for x in registry.all() if x.get("status")=="RUNNING" or x.get("decision")=="RUNNING"]
        if interrupted:
            for row in interrupted:registry.update(row["experiment_id"],status="INTERRUPTED",decision="FAILED",error="Process stopped before a result was persisted")
            raise ModelWorkflowError("INTERRUPTED_EXPERIMENT_REQUIRES_REVIEW")
        prior=next((x for x in reversed(loop.get("tested_actions",[])) if x.get("plan_id")==state.get("plan_id") and x.get("experiment_id")),None)
        if not prior:
            try:loop=manager.execute(loop["loop_id"])
            except Exception as exc:raise ModelWorkflowError(str(exc)) from exc
            prior=next((x for x in reversed(loop.get("tested_actions",[])) if x.get("plan_id")==state.get("plan_id")),{})
        outcome=prior.get("outcome");route="rollback" if outcome=="ROLLBACK" or loop.get("status")=="ROLLBACK" else "counterfactual_evaluate"
        return {"experiment_id":prior.get("experiment_id") or loop.get("latest_experiment_id"),"experiment_outcome":outcome,"current_business_state_id":loop.get("current_state_id"),"best_business_state_id":loop.get("best_state_id"),"last_stable_state_id":loop.get("last_stable_state_id"),"budget_remaining":int(loop.get("budget_remaining") or 0),"next_route":route}

    def evaluate_counterfactual(self,state):
        row=CounterfactualRegistry(self._root(state)).get(state.get("experiment_id")) if state.get("experiment_id") else None;decision=(row or {}).get("decision") or state.get("experiment_outcome")
        return {"experiment_outcome":decision,"next_route":"rollback" if decision in {"FAILED","UNSTABLE","ROLLBACK"} else "credit_update"}

    def update_credit(self,state):
        result=experiment_memory_service.refresh(state["dataset_id"]);return {"next_route":"shadow_reconcile","summaries":{**state.get("summaries",{}),"credit_update":result.get("created",0)}}

    def reconcile_shadow(self,state):
        rows=[x for x in shadow_service.predictions(state["dataset_id"],1000) if x.get("decision_id")==state.get("decision_id") and x.get("status")=="EVALUATED"]
        return {"shadow_prediction_ids":[x["shadow_id"] for x in rows] or state.get("shadow_prediction_ids",[]),"next_route":"next_decision"}

    def next_decision(self,state):
        loop=decision_agent_service.manager(state["dataset_id"]).get(state["decision_loop_id"]);budget=int(loop.get("budget_remaining") or 0);round_no=int(loop.get("round") or 0);status=loop.get("status")
        proceed=status=="RUNNING" and budget>0 and round_no<int(loop.get("budget",{}).get("max_rounds") or 3)
        return {"continue_workflow":proceed,"decision_round":round_no,"budget_remaining":budget,"next_route":"decision_context" if proceed else "end"}

    def rollback_business_state(self,state):
        manager=decision_agent_service.manager(state["dataset_id"]);loop=manager.get(state["decision_loop_id"])
        if loop.get("status")!="ROLLBACK":loop=manager.rollback(loop["loop_id"])
        return {"current_business_state_id":loop.get("current_state_id") or loop.get("last_stable_state_id"),"next_route":"end","continue_workflow":False,"summaries":{**state.get("summaries",{}),"rollback":"BUSINESS_STATE_RESTORED"}}
