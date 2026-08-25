from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import workflow_service as service

router=APIRouter(prefix="/api/workflows",tags=["workflow-orchestration"])


class StartBody(BaseModel):
    dataset_id:str
    segment:str="NEW"
    conversation_id:str|None=None
    entry_point:Literal["RUN_ALL","FROM_ANALYSIS","FROM_FEATURE","FROM_VALIDATION","FROM_DECISION","FROM_EXPERIMENT"]="RUN_ALL"
    selected_feature_id:str|None=None
    selected_hypothesis_id:str|None=None
    selected_proposal_id:str|None=None
    thread_id:str|None=None


class ResumeBody(BaseModel):payload:dict[str,Any]=Field(default_factory=dict)
class RetryBody(BaseModel):node:str|None=None


def guard(fn):
    try:return fn()
    except KeyError as exc:raise HTTPException(404,str(exc)) from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc


@router.get("/risk-research/definition")
def definition():return guard(service.definition)
@router.post("/risk-research/runs")
def start(body:StartBody):return guard(lambda:service.start(body.model_dump(exclude_none=True)))
@router.get("/runs/{run_id}")
def get(run_id:str):return guard(lambda:service.get(run_id))
@router.get("/runs/{run_id}/timeline")
def timeline(run_id:str):return guard(lambda:service.timeline(run_id))
@router.post("/runs/{run_id}/resume")
def resume(run_id:str,body:ResumeBody):return guard(lambda:service.resume(run_id,body.payload))
@router.post("/runs/{run_id}/approve")
def approve(run_id:str):return guard(lambda:service.approve(run_id))
@router.post("/runs/{run_id}/reject")
def reject(run_id:str):return guard(lambda:service.reject(run_id))
@router.post("/runs/{run_id}/cancel")
def cancel(run_id:str):return guard(lambda:service.cancel(run_id))
@router.post("/runs/{run_id}/retry-node")
def retry(run_id:str,body:RetryBody):return guard(lambda:service.retry_node(run_id,body.node))
@router.post("/runs/{run_id}/rollback")
def rollback(run_id:str):return guard(lambda:service.rollback(run_id))
