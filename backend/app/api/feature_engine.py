from __future__ import annotations
from typing import Any
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from ..services import feature_engine_service as service

engine_router=APIRouter(prefix='/api/feature-engine',tags=['feature-engine']);spec_router=APIRouter(prefix='/api/feature-specs',tags=['feature-specs']);feature_router=APIRouter(prefix='/api/features',tags=['features'])
class DatasetBody(BaseModel):dataset_id:str
class CompileBody(BaseModel):dataset_id:str;feature_spec_id:str|None=None;feature_spec:dict[str,Any]|None=None;available_data_sources:list[str]=Field(default_factory=lambda:['CURRENT_WIDE_TABLE'])
class ExecuteBody(BaseModel):dataset_id:str;user_confirmed:bool=False
class ProposalSpecBody(BaseModel):dataset_id:str
def guard(fn):
    try:return fn()
    except KeyError as exc:raise HTTPException(404,str(exc)) from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    except Exception as exc:
        code=getattr(exc,'code',None)
        if code:raise HTTPException(400,{'code':code,'message':str(exc),'details':getattr(exc,'details',{})}) from exc
        raise
@engine_router.get('/capabilities')
def capabilities():return service.capability_summary()
@engine_router.post('/compile')
def compile_feature(body:CompileBody):return guard(lambda:service.compile_payload(body.dataset_id,body.model_dump(exclude={'dataset_id'},exclude_none=True)))
@engine_router.get('/plans')
def plans(dataset_id:str):return guard(lambda:service.plans(dataset_id))
@engine_router.get('/plans/{plan_id}')
def plan(plan_id:str,dataset_id:str):return guard(lambda:service.plan(dataset_id,plan_id))
@engine_router.post('/execute/{plan_id}')
def execute(plan_id:str,body:ExecuteBody):return guard(lambda:service.execute_plan(body.dataset_id,plan_id,user_confirmed=body.user_confirmed))
@engine_router.get('/executions')
def executions(dataset_id:str):return guard(lambda:service.executions(dataset_id))
@engine_router.get('/executions/{execution_id}')
def execution(execution_id:str,dataset_id:str):return guard(lambda:service.execution(dataset_id,execution_id))
@engine_router.get('/gaps')
def gaps(dataset_id:str):return guard(lambda:service.gaps(dataset_id))
@spec_router.get('')
def specs(dataset_id:str):return guard(lambda:service.feature_specs(dataset_id))
@spec_router.get('/{spec_id}')
def spec(spec_id:str,dataset_id:str):return guard(lambda:service.feature_spec(dataset_id,spec_id))
@spec_router.post('/from-proposal/{proposal_id}')
def from_proposal(proposal_id:str,body:ProposalSpecBody):return guard(lambda:service.spec_from_proposal(body.dataset_id,proposal_id))
@feature_router.get('')
def features(dataset_id:str):return guard(lambda:service.generated_features(dataset_id))
@feature_router.post('/{feature_id}/rebuild')
def rebuild(feature_id:str,body:DatasetBody):return guard(lambda:service.rebuild_feature(body.dataset_id,feature_id))
