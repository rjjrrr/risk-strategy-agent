from fastapi import APIRouter, HTTPException
from core.context import ContextRequest
from ..services import agent_chat_service, context_service

router = APIRouter(prefix="/api/context", tags=["context"])


@router.post("/build")
def build_context(body: ContextRequest):
    try:
        return context_service.build(body, agent_chat_service.store)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{context_id}")
def get_context(context_id: str):
    result = context_service.load(context_id)
    if not result:
        raise HTTPException(404, "Context not found")
    return result


@router.get("/{context_id}/preview")
def get_context_preview(context_id: str):
    result = context_service.preview(context_id)
    if not result:
        raise HTTPException(404, "Context not found")
    return result
