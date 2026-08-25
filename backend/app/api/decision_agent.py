from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import decision_agent_service as service


router = APIRouter(prefix="/api/decision", tags=["decision-agent"])


class LoopCreateBody(BaseModel):
    dataset_id: str
    budget: dict[str, Any] = Field(default_factory=dict)


class DecisionBody(BaseModel):
    dataset_id: str
    loop_id: str | None = None
    use_llm: bool = False


class LoopActionBody(BaseModel):
    dataset_id: str | None = None
    use_llm: bool = False
    execute: bool = False
    decided_by: str = "HUMAN"
    reason: str = "HUMAN_STOP"


def guard(fn):
    try:
        return fn()
    except KeyError as exc:
        raise HTTPException(404, f"Not found: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/loops")
def create_loop(body: LoopCreateBody):
    return guard(lambda: service.create_loop(body.dataset_id, body.budget))


@router.get("/loops/{loop_id}")
def get_loop(loop_id: str, dataset_id: str | None = None):
    return guard(lambda: service.get_loop(loop_id, dataset_id))


@router.post("/diagnose")
def diagnose(body: DecisionBody):
    def run():
        loop = service.create_loop(body.dataset_id) if not body.loop_id else service.manager(body.dataset_id).get(body.loop_id)
        return service.manager(body.dataset_id).diagnose(loop["loop_id"], use_llm=body.use_llm)
    return guard(run)


@router.post("/plan")
def plan(body: DecisionBody):
    def run():
        mgr = service.manager(body.dataset_id)
        state = mgr.get(body.loop_id) if body.loop_id else service.create_loop(body.dataset_id)
        if not state.get("latest_plan_id"):
            state = mgr.diagnose(state["loop_id"], use_llm=body.use_llm)
        return mgr.plans.get(state.get("latest_plan_id"))
    return guard(run)


@router.post("/loops/{loop_id}/next")
def next_round(loop_id: str, body: LoopActionBody):
    def run():
        did = service.find_dataset(loop_id, body.dataset_id); mgr = service.manager(did)
        state = mgr.get(loop_id)
        if body.execute and state.get("latest_plan_id"):
            return mgr.execute(loop_id)
        return mgr.diagnose(loop_id, use_llm=body.use_llm)
    return guard(run)


@router.post("/loops/{loop_id}/execute")
def execute(loop_id: str, body: LoopActionBody):
    return guard(lambda: service.manager(service.find_dataset(loop_id, body.dataset_id)).execute(loop_id))


@router.post("/loops/{loop_id}/approve")
def approve(loop_id: str, body: LoopActionBody):
    return guard(lambda: service.manager(service.find_dataset(loop_id, body.dataset_id)).approve(loop_id, body.decided_by))


@router.post("/loops/{loop_id}/reject")
def reject(loop_id: str, body: LoopActionBody):
    return guard(lambda: service.manager(service.find_dataset(loop_id, body.dataset_id)).reject(loop_id, body.decided_by))


@router.post("/loops/{loop_id}/rollback")
def rollback(loop_id: str, body: LoopActionBody):
    return guard(lambda: service.manager(service.find_dataset(loop_id, body.dataset_id)).rollback(loop_id))


@router.post("/loops/{loop_id}/stop")
def stop(loop_id: str, body: LoopActionBody):
    return guard(lambda: service.manager(service.find_dataset(loop_id, body.dataset_id)).stop(loop_id, body.reason))
