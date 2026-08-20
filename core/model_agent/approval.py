from __future__ import annotations

import uuid
from typing import Any

from .registry import ApprovalRegistry, utc_now
from .state import ModelAgentStateStore


HUMAN_REQUIRED_ACTIONS = {
    "PERMANENT_FEATURE_REMOVE", "PRODUCTION_FEATURE_APPROVAL", "SEGMENT_MODEL_SPLIT",
    "TARGET_CHANGE", "BAD_LABEL_CHANGE", "SEGMENT_MAPPING_CHANGE", "PERMANENT_LEAKAGE_EXCLUDE",
}


class HumanApprovalManager:
    def __init__(self, registry: ApprovalRegistry, state_store: ModelAgentStateStore):
        self.registry=registry; self.state_store=state_store

    def propose(self, action_type: str, payload: dict[str, Any], reason: str, impact: str) -> dict[str, Any]:
        if action_type not in HUMAN_REQUIRED_ACTIONS:
            raise ValueError(f"Action does not require human approval: {action_type}")
        row={"approval_id":f"A_{uuid.uuid4().hex[:10]}","action_type":action_type,"payload":payload,"reason":reason,"impact":impact,"status":"PENDING","decision":None,"decision_time":None}
        self.registry.add(row); state=self.state_store.load(); state["pending_human_approval"].append(row["approval_id"]); self.state_store.save(state); return row

    def decide(self, approval_id: str, decision: str, decided_by: str = "HUMAN") -> dict[str, Any]:
        if decision not in {"APPROVE", "REJECT"}: raise ValueError("decision must be APPROVE or REJECT")
        row=self.registry.update(approval_id,status="APPROVED" if decision=="APPROVE" else "REJECTED",decision=decision,decision_time=utc_now(),decided_by=decided_by)
        state=self.state_store.load(); state["pending_human_approval"]=[x for x in state["pending_human_approval"] if x!=approval_id]; self.state_store.save(state); return row
