from __future__ import annotations

import uuid

from langgraph.types import Command

from core.workflow.adapters import WorkflowAdapters
from core.workflow.checkpoint import SQLiteCheckpointBackend
from core.workflow.exceptions import LLMWorkflowError, ModelWorkflowError
from core.workflow.graph import NODE_NAMES, RiskResearchWorkflow
from core.workflow.registry import WorkflowRegistry
from core.workflow.state import assert_lightweight, initial_state


class FakeAdapters(WorkflowAdapters):
    def __init__(self,*,leakage=False,review=False,approval=False,model_failure=False,llm_failure=False,budget_stop=False):
        self.leakage=leakage;self.review=review;self.approval=approval;self.model_failure=model_failure;self.llm_failure=llm_failure;self.budget_stop=budget_stop;self.calls={}
    def hit(self,name):self.calls[name]=self.calls.get(name,0)+1
    def build_context(self,state):self.hit("context");return {"context_id":"CTX1","context_hash":"HASH1","next_route":"analysis"}
    def analyze(self,state):
        self.hit("analysis")
        if self.llm_failure:raise LLMWorkflowError("provider unavailable")
        return {"proposal_ids":["P1"],"next_route":"proposal_guard"}
    def guard_proposals(self,state):self.hit("guard");return {"next_route":"end" if self.leakage else "human_review_proposal","warnings":["LEAKAGE_RISK"] if self.leakage else []}
    def review_proposals(self,state,approved):self.hit("proposal_review");return {"feature_ids":["F_PROPOSED"] if approved else [],"next_route":"feature_compile" if approved else "end"}
    def compile_feature(self,state):self.hit("compile");return {"feature_spec_ids":["FS1"],"plan_id":"FP1","next_route":"feature_execute"}
    def execute_feature(self,state):self.hit("feature_execute");return {"feature_ids":["F1"],"next_route":"cheap_validation"}
    def validate_feature(self,state):self.hit("validation");return {"validation_ids":["V1"],"validation_decision":"REVIEW" if self.review else "PROMISING","review_type":"FEATURE_REVIEW" if self.review else None,"next_route":"review" if self.review else "decision_context"}
    def build_decision_context(self,state):self.hit("decision_context");return {"decision_loop_id":"DL1","budget_remaining":0 if self.budget_stop else 6,"current_business_state_id":"BS_CURRENT","best_business_state_id":"BS_BEST","last_stable_state_id":"BS_STABLE","next_route":"decision"}
    def decide(self,state):
        self.hit("decision")
        if self.budget_stop:return {"next_route":"end","continue_workflow":False,"warnings":["BUDGET_EXHAUSTED"]}
        return {"decision_id":"D1","plan_id":"EP1","decision_action":"TEST_FEATURE","requires_approval":self.approval,"decision_round":1,"next_route":"experiment_plan","summaries":{"final_selection_policy":"PHASE5","selected_candidate":"F_PHASE5"}}
    def plan_experiment(self,state):self.hit("plan");return {"requires_approval":self.approval,"next_route":"shadow_predict"}
    def predict_shadow(self,state):self.hit("shadow_predict");return {"shadow_prediction_ids":["SH1"],"next_route":"approval_gate","summaries":{**state.get("summaries",{}),"shadow_rank_1":"F_SHADOW","final_selection_policy":"PHASE5"}}
    def approve_action(self,state,approved):self.hit("approval");return {"next_route":"experiment_execute" if approved else "next_decision"}
    def execute_experiment(self,state):
        self.hit("experiment_execute")
        if self.model_failure:raise ModelWorkflowError("training failed")
        return {"experiment_id":"EXP1","experiment_outcome":"POSITIVE","budget_remaining":5,"next_route":"counterfactual_evaluate","summaries":{**state.get("summaries",{}),"executed_candidate":"F_PHASE5"}}
    def evaluate_counterfactual(self,state):self.hit("evaluate");return {"experiment_outcome":"POSITIVE","next_route":"credit_update"}
    def update_credit(self,state):self.hit("credit");return {"next_route":"shadow_reconcile"}
    def reconcile_shadow(self,state):self.hit("shadow_reconcile");return {"next_route":"next_decision"}
    def next_decision(self,state):self.hit("next");return {"continue_workflow":False,"next_route":"end"}
    def rollback_business_state(self,state):self.hit("rollback");return {"current_business_state_id":"BS_STABLE","summaries":{**state.get("summaries",{}),"rollback":"RESTORED"},"continue_workflow":False,"next_route":"end"}


def harness(tmp_path,adapters,entry="RUN_ALL",feature=None):
    registry=WorkflowRegistry(tmp_path/"audit.sqlite3");checkpoint=SQLiteCheckpointBackend(tmp_path/"checkpoints.sqlite3");workflow=RiskResearchWorkflow(adapters,registry,checkpoint.saver);run_id=f"RUN_{uuid.uuid4().hex[:8]}";thread_id=f"THREAD_{uuid.uuid4().hex[:8]}"
    registry.create_run({"run_id":run_id,"thread_id":thread_id,"workflow_version":"risk-research-v1","dataset_id":"DS","segment":"NEW","entry_point":entry})
    state=initial_state(run_id=run_id,thread_id=thread_id,dataset_id="DS",entry_point=entry,selected_feature_id=feature)
    return workflow,registry,state,{"configurable":{"thread_id":thread_id}}


def approve_first(workflow,state,config):
    first=workflow.graph.invoke(state,config);assert first.get("__interrupt__")
    return workflow.graph.invoke(Command(resume={"approved":True}),config)


def test_graph_compile(tmp_path):
    workflow,_,_,_=harness(tmp_path,FakeAdapters());definition=workflow.definition()
    assert set(NODE_NAMES)==set(definition["nodes"]);assert any(x["conditional"] for x in definition["edges"])
    from backend.app.main import app
    paths=app.openapi()["paths"]
    assert all(path in paths for path in ["/api/workflows/risk-research/runs","/api/workflows/runs/{run_id}","/api/workflows/runs/{run_id}/timeline","/api/workflows/runs/{run_id}/resume","/api/workflows/runs/{run_id}/approve","/api/workflows/runs/{run_id}/reject","/api/workflows/runs/{run_id}/cancel","/api/workflows/runs/{run_id}/retry-node"])


def test_graph_happy_path(tmp_path):
    adapter=FakeAdapters();workflow,registry,state,config=harness(tmp_path,adapter);result=approve_first(workflow,state,config)
    assert result["experiment_outcome"]=="POSITIVE" and result["current_business_state_id"]=="BS_CURRENT"
    assert adapter.calls["feature_execute"]==adapter.calls["experiment_execute"]==adapter.calls["credit"]==1
    assert registry.timeline(state["run_id"])[-1]["node"]=="next_decision"


def test_graph_proposal_reject(tmp_path):
    adapter=FakeAdapters();workflow,_,state,config=harness(tmp_path,adapter);first=workflow.graph.invoke(state,config);result=workflow.graph.invoke(Command(resume={"approved":False}),config)
    assert result["approval_status"]=="REJECTED" and adapter.calls.get("compile",0)==0


def test_graph_leakage_stop(tmp_path):
    adapter=FakeAdapters(leakage=True);workflow,_,state,config=harness(tmp_path,adapter);result=workflow.graph.invoke(state,config)
    assert "LEAKAGE_RISK" in result["warnings"] and adapter.calls.get("compile",0)==0 and not result.get("__interrupt__")


def test_graph_review_interrupt(tmp_path):
    adapter=FakeAdapters(review=True);workflow,_,state,config=harness(tmp_path,adapter);after_proposal=approve_first(workflow,state,config)
    assert after_proposal.get("__interrupt__");result=workflow.graph.invoke(Command(resume={"approved":True}),config)
    assert result["validation_decision"]=="REVIEW" and adapter.calls["decision"]==1


def test_graph_approval_resume(tmp_path):
    adapter=FakeAdapters(approval=True);workflow,_,state,config=harness(tmp_path,adapter);after_proposal=approve_first(workflow,state,config)
    assert after_proposal.get("__interrupt__");result=workflow.graph.invoke(Command(resume={"approved":True}),config)
    assert adapter.calls["approval"]==1 and adapter.calls["experiment_execute"]==1 and result["experiment_id"]=="EXP1"


def test_graph_model_failure_rollback(tmp_path):
    adapter=FakeAdapters(model_failure=True);workflow,registry,state,config=harness(tmp_path,adapter);result=approve_first(workflow,state,config)
    assert result["current_business_state_id"]=="BS_STABLE" and adapter.calls["rollback"]==1
    assert [x["node"] for x in registry.timeline(state["run_id"])[-2:]]==["experiment_execute","rollback_node"]


def test_graph_crash_resume(tmp_path):
    adapter=FakeAdapters();workflow,_,state,config=harness(tmp_path,adapter,entry="FROM_FEATURE");result=workflow.graph.invoke(state,config,interrupt_after=["feature_execute"])
    assert workflow.graph.get_state(config).next==("cheap_validation",);workflow.graph.invoke(None,config)
    assert adapter.calls["feature_execute"]==1 and adapter.calls["validation"]==1


def test_graph_no_duplicate_feature_execute(tmp_path):
    adapter=FakeAdapters();workflow,_,state,config=harness(tmp_path,adapter,entry="FROM_FEATURE");workflow.graph.invoke(state,config,interrupt_after=["feature_execute"]);workflow.graph.invoke(None,config)
    assert adapter.calls["feature_execute"]==1


def test_graph_no_duplicate_experiment(tmp_path):
    adapter=FakeAdapters();workflow,_,state,config=harness(tmp_path,adapter,entry="FROM_DECISION");workflow.graph.invoke(state,config,interrupt_after=["experiment_execute"]);workflow.graph.invoke(None,config)
    assert adapter.calls["experiment_execute"]==1


def test_graph_credit_resume(tmp_path):
    adapter=FakeAdapters();workflow,_,state,config=harness(tmp_path,adapter,entry="FROM_DECISION");workflow.graph.invoke(state,config,interrupt_after=["experiment_execute"]);assert adapter.calls.get("credit",0)==0;workflow.graph.invoke(None,config)
    assert adapter.calls["credit"]==1 and adapter.calls["experiment_execute"]==1


def test_graph_budget_stop(tmp_path):
    adapter=FakeAdapters(budget_stop=True);workflow,_,state,config=harness(tmp_path,adapter,entry="FROM_DECISION");result=workflow.graph.invoke(state,config)
    assert "BUDGET_EXHAUSTED" in result["warnings"] and adapter.calls.get("experiment_execute",0)==0


def test_graph_shadow_guard(tmp_path):
    adapter=FakeAdapters();workflow,_,state,config=harness(tmp_path,adapter,entry="FROM_DECISION");result=workflow.graph.invoke(state,config)
    assert result["summaries"]["shadow_rank_1"]=="F_SHADOW" and result["summaries"]["executed_candidate"]=="F_PHASE5" and result["summaries"]["final_selection_policy"]=="PHASE5"


def test_graph_llm_failure(tmp_path):
    adapter=FakeAdapters(llm_failure=True);workflow,_,state,config=harness(tmp_path,adapter);result=workflow.graph.invoke(state,config)
    assert result.get("__interrupt__");workflow.graph.invoke(Command(resume={"approved":False}),config)
    assert adapter.calls.get("feature_execute",0)==0 and adapter.calls["analysis"]==1


def test_graph_cancel(tmp_path):
    adapter=FakeAdapters();workflow,registry,state,config=harness(tmp_path,adapter);first=workflow.graph.invoke(state,config);assert first.get("__interrupt__")
    registry.update_run(state["run_id"],status="CANCELLED",cancel_requested=1);assert registry.get_run(state["run_id"])["status"]=="CANCELLED" and adapter.calls.get("compile",0)==0


def test_graph_checkpoint_business_state_separation(tmp_path):
    adapter=FakeAdapters(model_failure=True);workflow,registry,state,config=harness(tmp_path,adapter,entry="FROM_DECISION");result=workflow.graph.invoke(state,config);assert_lightweight(result)
    nodes=[x["node"] for x in registry.timeline(state["run_id"])]
    assert nodes.index("experiment_execute")<nodes.index("rollback_node") and result["current_business_state_id"]=="BS_STABLE"
    assert "DataFrame" not in str(workflow.graph.get_state(config).values)
