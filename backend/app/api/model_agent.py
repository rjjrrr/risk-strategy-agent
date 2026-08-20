from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..services import model_agent_service as service

router = APIRouter(prefix="/api/model-agent", tags=["model-agent"])


class RunRequest(BaseModel):
    application_time_field: str | None = None


class StopRequest(BaseModel):
    reason: str = "HUMAN_STOP"


class RollbackRequest(BaseModel):
    state_id: str | None = None


class ApprovalProposal(BaseModel):
    action_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str
    impact: str


class ApprovalDecision(BaseModel):
    decision: str
    decided_by: str = "HUMAN"


def guarded(fn):
    try:
        return fn()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{dataset_id}/run")
def run(dataset_id: str, request: RunRequest = RunRequest()): return guarded(lambda: service.run_initial(dataset_id, request.application_time_field))


@router.post("/{dataset_id}/next-experiment")
def next_experiment(dataset_id: str): return guarded(lambda: service.run_next(dataset_id))


@router.post("/{dataset_id}/round")
def run_round(dataset_id: str): return guarded(lambda: service.run_next(dataset_id))


@router.post("/{dataset_id}/stop")
def stop(dataset_id: str, request: StopRequest): return guarded(lambda: service.stop(dataset_id, request.reason))


@router.post("/{dataset_id}/rollback")
def rollback(dataset_id: str, request: RollbackRequest = RollbackRequest()): return guarded(lambda: service.rollback(dataset_id, request.state_id))


@router.get("/{dataset_id}/state")
def state(dataset_id: str): return guarded(lambda: service.agent(dataset_id).state_store.load())


@router.get("/{dataset_id}/summary")
def summary(dataset_id: str): return guarded(lambda: service.summary(dataset_id))


@router.get("/{dataset_id}/semantics")
def semantics(dataset_id: str): return guarded(lambda: service.semantics(dataset_id))


@router.get("/{dataset_id}/timeline")
def timeline(dataset_id: str): return guarded(lambda: service.timeline(dataset_id))


for artifact in ("hypotheses", "features", "experiments", "diagnoses", "approvals"):
    router.add_api_route(f"/{{dataset_id}}/{artifact}", lambda dataset_id, kind=artifact: guarded(lambda: service.list_artifact(dataset_id, kind)), methods=["GET"], name=f"model_agent_{artifact}")


@router.post("/{dataset_id}/approvals")
def propose(dataset_id: str, request: ApprovalProposal): return guarded(lambda: service.propose_approval(dataset_id, request.action_type, request.payload, request.reason, request.impact))


@router.post("/{dataset_id}/approvals/{approval_id}/decision")
def decide(dataset_id: str, approval_id: str, request: ApprovalDecision): return guarded(lambda: service.decide_approval(dataset_id, approval_id, request.decision, request.decided_by))


@router.get("/{dataset_id}/report")
def report(dataset_id: str):
    path = guarded(lambda: service.write_report(dataset_id))
    return FileResponse(path, media_type="text/markdown", filename=f"{dataset_id}_model_report.md")
