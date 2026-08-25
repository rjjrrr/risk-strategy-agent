from fastapi import APIRouter,HTTPException
from pydantic import BaseModel
from ..services import shadow_service as service
router=APIRouter(prefix="/api/shadow",tags=["surrogate-shadow"])
class ConfirmBody(BaseModel):dataset_id:str;user_confirmed:bool=False
def guard(fn):
    try:return fn()
    except KeyError as exc:raise HTTPException(404,str(exc)) from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@router.get("/status")
def status(dataset_id:str):return guard(lambda:service.status(dataset_id))
@router.get("/predictions")
def predictions(dataset_id:str,limit:int=200):return guard(lambda:service.predictions(dataset_id,limit))
@router.get("/predictions/{shadow_id}")
def prediction(shadow_id:str,dataset_id:str):return guard(lambda:service.prediction(dataset_id,shadow_id))
@router.post("/predictions/{shadow_id}/comparison")
def comparison(shadow_id:str,body:ConfirmBody):return guard(lambda:service.authorize_comparison(body.dataset_id,shadow_id,body.user_confirmed))
@router.get("/evaluation")
def evaluation(dataset_id:str):return guard(lambda:service.evaluation(dataset_id))
@router.get("/errors")
def errors(dataset_id:str):return guard(lambda:service.errors(dataset_id))
@router.get("/checkpoints")
def checkpoints(dataset_id:str):return guard(lambda:service.checkpoints(dataset_id))
@router.post("/retrain")
def retrain(body:ConfirmBody):return guard(lambda:service.retrain(body.dataset_id,body.user_confirmed))
@router.get("/models")
def models(dataset_id:str):return guard(lambda:service.models(dataset_id))
@router.post("/models/{surrogate_id}/promote")
def promote(surrogate_id:str,body:ConfirmBody):return guard(lambda:service.promote(body.dataset_id,surrogate_id,body.user_confirmed))
