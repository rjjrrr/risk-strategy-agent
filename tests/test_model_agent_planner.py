from core.model_agent.approval import HumanApprovalManager
from core.model_agent.planner import PlannerAgent
from core.model_agent.registry import ApprovalRegistry
from core.model_agent.state import ModelAgentStateStore


def test_planner_priority_and_stop_conditions():
    hypotheses=[{'hypothesis_id':'H1','status':'PROPOSED','confidence':'MEDIUM','estimated_cost':'LOW','risk_mechanism':'m','expected_benefit':'x'},{'hypothesis_id':'H2','status':'PROPOSED','confidence':'HIGH','estimated_cost':'LOW','risk_mechanism':'best','expected_benefit':'x'}]
    plan=PlannerAgent().choose(hypotheses,[],{'experiments':2})
    assert plan['hypothesis_id']=='H2'
    state={'round_index':3,'max_rounds':3,'pending_human_approval':[],'budget':{'experiments':2}}
    assert PlannerAgent.stop_reason(state,[])=='MAX_AGENT_ROUNDS_REACHED'
    state['round_index']=1
    assert PlannerAgent.stop_reason(state,[{'decision':'REJECT'},{'decision':'REJECT'}])=='TWO_ROUNDS_WITHOUT_MATERIAL_IMPROVEMENT'


def test_empty_experiment_history_does_not_stop_before_planning():
    state={'round_index':0,'max_rounds':3,'pending_human_approval':[],'budget':{'experiments':6}}
    assert PlannerAgent.stop_reason(state,[],high_confidence_remaining=False) is None


def test_medium_confidence_work_can_continue_after_one_round():
    state={'round_index':1,'max_rounds':3,'pending_human_approval':[],'budget':{'experiments':5}}
    assert PlannerAgent.stop_reason(state,[{'decision':'ACCEPT_PERFORMANCE'}],high_confidence_remaining=False) is None


def test_human_approval_flow(tmp_path):
    store=ModelAgentStateStore(tmp_path,'d');store.create(); manager=HumanApprovalManager(ApprovalRegistry(tmp_path),store)
    proposal=manager.propose('PERMANENT_FEATURE_REMOVE',{'features':['x']},'high PSI','challenger excludes x')
    assert proposal['approval_id'] in store.load()['pending_human_approval']
    decision=manager.decide(proposal['approval_id'],'REJECT')
    assert decision['status']=='REJECTED' and not store.load()['pending_human_approval']
