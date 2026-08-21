from __future__ import annotations
from typing import Any
from fastapi import APIRouter,HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,Field
from core.llm.schemas import LLMBindingInput
from core.llm.exceptions import LLMError
from ..services import agent_chat_service as service

llm_router=APIRouter(prefix='/api/llm',tags=['llm-bindings']);chat_router=APIRouter(prefix='/api/agent-chat',tags=['agent-chat'])
class ConversationInput(BaseModel):title:str='New chat';agent_type:str='GENERAL_CHAT';default_binding_id:str|None=None;dataset_id:str|None=None;experiment_id:str|None=None;state_id:str|None=None
class MessageInput(BaseModel):
    content:str;agent_type:str|None=None;binding_id:str|None=None
    attachments:list[dict[str,Any]]=Field(default_factory=list);parent_message_id:str|None=None
    context_options:dict[str,Any]=Field(default_factory=dict);focus_fields:list[str]=Field(default_factory=list)
class DecisionInput(BaseModel):decision:str

def guard(fn):
    try:return fn()
    except KeyError as e:raise HTTPException(404,str(e)) from e
    except LLMError as e:raise HTTPException(503,{'code':e.code,'message':str(e)}) from e
    except ValueError as e:raise HTTPException(400,str(e)) from e
@llm_router.get('/bindings')
def get_bindings():return service.binding_views()
@llm_router.post('/bindings')
def create_binding(body:LLMBindingInput):return guard(lambda:service.bindings.create(body))
@llm_router.patch('/bindings/{binding_id}')
def patch_binding(binding_id:str,body:dict[str,Any]):return guard(lambda:service.bindings.update(binding_id,body))
@llm_router.delete('/bindings/{binding_id}')
def delete_binding(binding_id:str):service.bindings.delete(binding_id);return {'deleted':True}
@llm_router.post('/bindings/{binding_id}/test')
def test_binding(binding_id:str):
    try:return service.runtime.test_connection(binding_id)
    except Exception as e:return {'status':'FAILED','latency_ms':None,'model':guard(lambda:service.bindings.raw(binding_id))['model'],'error_summary':str(e)[:200],'error_type':getattr(e,'code','PROVIDER_ERROR')}
@llm_router.get('/prompts')
def get_prompts():return service.prompts.all()
@llm_router.get('/agent-defaults')
def agent_defaults():return service.prompts.defaults()
@llm_router.put('/agent-defaults/{agent_type}')
def set_agent_default(agent_type:str,body:dict[str,Any]):return guard(lambda:service.prompts.set_default_binding(agent_type,body['binding_id']))
@chat_router.post('/conversations')
def create_conversation(body:ConversationInput):return service.store.create_conversation(**body.model_dump())
@chat_router.get('/conversations')
def conversations(search:str|None=None):return service.store.conversations(search)
@chat_router.get('/conversations/{cid}')
def conversation(cid:str):return guard(lambda:service.store.conversation(cid))
@chat_router.patch('/conversations/{cid}')
def patch_conversation(cid:str,body:dict[str,Any]):return guard(lambda:service.store.update_conversation(cid,body))
@chat_router.delete('/conversations/{cid}')
def delete_conversation(cid:str):return guard(lambda:service.store.delete_conversation(cid))
@chat_router.post('/conversations/{cid}/messages')
def message(cid:str,body:MessageInput):return guard(lambda:service.send(cid,**body.model_dump()))
@chat_router.post('/conversations/{cid}/messages/stream')
def message_stream(cid:str,body:MessageInput):return StreamingResponse(service.stream(cid,**body.model_dump()),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
@chat_router.post('/messages/{mid}/cancel')
def cancel(mid:str):return {'cancelled':service.cancel(mid)}
@chat_router.post('/conversations/{cid}/messages/{mid}/retry')
def retry(cid:str,mid:str,body:MessageInput):return guard(lambda:service.send(cid,body.content,body.agent_type,body.binding_id,body.attachments,mid,body.context_options,body.focus_fields))
@chat_router.get('/proposals')
def proposals(conversation_id:str|None=None):return service.store.proposals(conversation_id)
@chat_router.post('/proposals/{pid}/accept')
def accept(pid:str):return guard(lambda:service.decide_proposal(pid,True))
@chat_router.post('/proposals/{pid}/reject')
def reject(pid:str):return guard(lambda:service.decide_proposal(pid,False))
@chat_router.get('/calls')
def calls(conversation_id:str|None=None,agent_type:str|None=None,binding_id:str|None=None,success:bool|None=None):return service.store.calls(locals())
