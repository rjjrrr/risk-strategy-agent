from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from langgraph.types import Command

from core.workflow.checkpoint import SQLiteCheckpointBackend
from core.workflow.graph import RiskResearchWorkflow, WORKFLOW_VERSION
from core.workflow.registry import WorkflowRegistry
from core.workflow.state import initial_state, utc_now
from .. import config
from .analysis_service import get_dataset
from .workflow_adapters import ServiceWorkflowAdapters


class WorkflowRuntime:
    def __init__(self,root:Path,adapters=None):
        root.mkdir(parents=True,exist_ok=True);self.registry=WorkflowRegistry(root/"workflow_audit.sqlite3");self.checkpoints=SQLiteCheckpointBackend(root/"workflow_checkpoints.sqlite3");self.workflow=RiskResearchWorkflow(adapters or ServiceWorkflowAdapters(),self.registry,self.checkpoints.saver)

    @staticmethod
    def _config(thread_id):return {"configurable":{"thread_id":thread_id}}

    def start(self,payload:dict[str,Any]):
        get_dataset(payload["dataset_id"]);run_id=f"WFR_{uuid.uuid4().hex[:12]}";thread_id=payload.get("thread_id") or f"WFT_{uuid.uuid4().hex[:12]}";state_payload={k:v for k,v in payload.items() if k!="thread_id"};state=initial_state(run_id=run_id,thread_id=thread_id,workflow_version=WORKFLOW_VERSION,**state_payload)
        self.registry.create_run({"run_id":run_id,"thread_id":thread_id,"workflow_version":WORKFLOW_VERSION,"dataset_id":payload["dataset_id"],"segment":payload.get("segment","NEW"),"entry_point":payload.get("entry_point","RUN_ALL")})
        started=time.perf_counter();result=self.workflow.graph.invoke(state,self._config(thread_id));return self._sync(run_id,result,round((time.perf_counter()-started)*1000,3))

    def _sync(self,run_id,result,overhead_ms=0):
        run=self.registry.get_run(run_id);snapshot=self.workflow.graph.get_state(self._config(run["thread_id"]));values=dict(snapshot.values);checkpoint_id=snapshot.config.get("configurable",{}).get("checkpoint_id");waiting=bool(result.get("__interrupt__")) if isinstance(result,dict) else bool(snapshot.tasks and any(getattr(x,"interrupts",None) for x in snapshot.tasks));failed=bool(values.get("errors")) and not snapshot.next
        status="WAITING" if waiting else "FAILED" if failed else "SUCCESS" if not snapshot.next else "RUNNING";finished=utc_now() if status in {"SUCCESS","FAILED"} else None
        current_node=run.get("current_node") if waiting else values.get("current_node");run=self.registry.update_run(run_id,status=status,current_node=current_node,checkpoint_id=checkpoint_id,business_state_id=values.get("current_business_state_id"),finished_at=finished)
        if waiting:values["node_status"]={**values.get("node_status",{}),current_node:"WAITING"};values["current_node"]=current_node
        return {"run":run,"state":values,"interrupts":[getattr(x,"value",x) for x in result.get("__interrupt__",[])] if isinstance(result,dict) else [],"orchestration_overhead_ms":overhead_ms}

    def get(self,run_id):
        run=self.registry.get_run(run_id);snapshot=self.workflow.graph.get_state(self._config(run["thread_id"]));values=dict(snapshot.values)
        if run["status"]=="WAITING":values["node_status"]={**values.get("node_status",{}),run.get("current_node"):"WAITING"};values["current_node"]=run.get("current_node")
        return {"run":run,"state":values,"next_nodes":list(snapshot.next)}

    def timeline(self,run_id):return {"run":self.registry.get_run(run_id),"items":self.registry.timeline(run_id)}

    def resume(self,run_id,payload):
        run=self.registry.get_run(run_id)
        if run["status"]=="CANCELLED":raise ValueError("WORKFLOW_CANCELLED")
        if not run.get("checkpoint_id"):raise ValueError("NO_CHECKPOINT")
        started=time.perf_counter();result=self.workflow.graph.invoke(Command(resume=payload),self._config(run["thread_id"]));return self._sync(run_id,result,round((time.perf_counter()-started)*1000,3))

    def decide(self,run_id,approved):return self.resume(run_id,{"approved":approved,"decided_by":"HUMAN"})

    def cancel(self,run_id):
        run=self.registry.get_run(run_id);status="CANCELLED" if run["status"]=="WAITING" else "CANCEL_REQUESTED";self.registry.event(run_id,"USER_CANCEL",status,{"previous_status":run["status"]});return self.registry.update_run(run_id,status=status,cancel_requested=1,finished_at=utc_now() if status=="CANCELLED" else None)

    def retry_node(self,run_id,node=None):
        run=self.registry.get_run(run_id);state=self.get(run_id)["state"];node=node or state.get("current_node")
        if node not in {"analysis","decision","build_context","feature_compile","feature_execute","cheap_validation","experiment_execute"}:raise ValueError("NODE_NOT_RETRYABLE")
        counts=dict(state.get("retry_counts") or {});limit=1 if node in {"analysis","decision"} else 1
        if counts.get(node,0)>=limit:raise ValueError("RETRY_LIMIT_REACHED")
        counts[node]=counts.get(node,0)+1;result=self.workflow.graph.invoke(Command(goto=node,update={"retry_counts":counts,"errors":[],"next_route":None}),self._config(run["thread_id"]));return self._sync(run_id,result)

    def rollback(self,run_id):
        run=self.registry.get_run(run_id);result=self.workflow.graph.invoke(Command(goto="rollback_node",update={"errors":[],"next_route":None}),self._config(run["thread_id"]));return self._sync(run_id,result)

    def definition(self):return self.workflow.definition()


runtime=WorkflowRuntime(config.RUNTIME_DIR/"workflow")
def start(payload):return runtime.start(payload)
def get(run_id):return runtime.get(run_id)
def timeline(run_id):return runtime.timeline(run_id)
def resume(run_id,payload):return runtime.resume(run_id,payload)
def approve(run_id):return runtime.decide(run_id,True)
def reject(run_id):return runtime.decide(run_id,False)
def cancel(run_id):return runtime.cancel(run_id)
def retry_node(run_id,node=None):return runtime.retry_node(run_id,node)
def rollback(run_id):return runtime.rollback(run_id)
def definition():return runtime.definition()
