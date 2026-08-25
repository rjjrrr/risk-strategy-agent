from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import WorkflowNodes
from .routing import entry_route, route
from .state import RiskGraphState

WORKFLOW_VERSION="risk-research-v1"
NODE_NAMES=("entry_router","build_context","analysis","proposal_guard","human_review_proposal","feature_compile","feature_review","feature_execute","cheap_validation","decision_context","decision","experiment_plan","shadow_predict","approval_gate","experiment_execute","counterfactual_evaluate","credit_update","shadow_reconcile","next_decision","rollback_node")


class RiskResearchWorkflow:
    def __init__(self,adapters,registry,checkpointer):
        self.nodes=WorkflowNodes(adapters,registry);builder=StateGraph(RiskGraphState)
        for name in NODE_NAMES:builder.add_node(name,getattr(self.nodes,name))
        builder.add_edge(START,"entry_router")
        builder.add_conditional_edges("entry_router",entry_route,{"build_context":"build_context","feature_compile":"feature_compile","cheap_validation":"cheap_validation","decision_context":"decision_context","shadow_predict":"shadow_predict","end":END})
        builder.add_edge("build_context","analysis")
        builder.add_conditional_edges("analysis",lambda s:route(s,"proposal_guard"),{"proposal_guard":"proposal_guard","review":"feature_review","end":END})
        builder.add_conditional_edges("proposal_guard",lambda s:route(s,"human_review_proposal"),{"human_review_proposal":"human_review_proposal","feature_compile":"feature_compile","review":"human_review_proposal","end":END})
        builder.add_conditional_edges("human_review_proposal",lambda s:route(s,"end"),{"feature_compile":"feature_compile","end":END})
        builder.add_conditional_edges("feature_compile",lambda s:route(s,"feature_execute"),{"feature_execute":"feature_execute","review":"feature_review","end":END})
        builder.add_conditional_edges("feature_review",lambda s:route(s,"end"),{"feature_execute":"feature_execute","decision_context":"decision_context","end":END})
        builder.add_edge("feature_execute","cheap_validation")
        builder.add_conditional_edges("cheap_validation",lambda s:route(s,"decision_context"),{"decision_context":"decision_context","review":"feature_review","credit_update":"credit_update","end":END})
        builder.add_edge("decision_context","decision")
        builder.add_conditional_edges("decision",lambda s:route(s,"experiment_plan"),{"experiment_plan":"experiment_plan","rollback":"rollback_node","review":"feature_review","end":END})
        builder.add_edge("experiment_plan","shadow_predict");builder.add_edge("shadow_predict","approval_gate")
        builder.add_conditional_edges("approval_gate",lambda s:route(s,"experiment_execute"),{"experiment_execute":"experiment_execute","next_decision":"next_decision","end":END})
        builder.add_conditional_edges("experiment_execute",lambda s:route(s,"counterfactual_evaluate"),{"counterfactual_evaluate":"counterfactual_evaluate","rollback":"rollback_node","end":END})
        builder.add_conditional_edges("counterfactual_evaluate",lambda s:route(s,"credit_update"),{"credit_update":"credit_update","rollback":"rollback_node","end":END})
        builder.add_edge("credit_update","shadow_reconcile");builder.add_edge("shadow_reconcile","next_decision")
        builder.add_conditional_edges("next_decision",lambda s:route(s,"end"),{"decision_context":"decision_context","end":END})
        builder.add_conditional_edges("rollback_node",lambda s:route(s,"end"),{"next_decision":"next_decision","end":END})
        self.builder=builder;self.graph=builder.compile(checkpointer=checkpointer)

    def definition(self):
        view=self.graph.get_graph();return {"workflow_version":WORKFLOW_VERSION,"nodes":sorted(x for x in view.nodes if not x.startswith("__")),"edges":[{"source":e.source,"target":e.target,"conditional":bool(e.conditional)} for e in view.edges]}
