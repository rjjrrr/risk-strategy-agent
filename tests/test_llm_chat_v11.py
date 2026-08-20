import json,sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app import config
from backend.app.main import app
from backend.app.services import agent_chat_service as service
from core.llm.bindings import BindingStore
from core.llm.exceptions import AuthError,NoActiveBinding,ProviderTimeout,RateLimitError
from core.llm.prompts import PromptRegistry
from core.llm.provider import MockProvider
from core.llm.runtime import LLMRuntime
from core.llm.schemas import LLMBindingInput
from core.llm.storage import ChatStore


@pytest.fixture
def llm_env(tmp_path,monkeypatch):
    db=tmp_path/'chat.sqlite3';bs=BindingStore(db);pr=PromptRegistry(db);cs=ChatStore(db);rt=LLMRuntime(bs,pr)
    monkeypatch.setattr(service,'bindings',bs);monkeypatch.setattr(service,'prompts',pr);monkeypatch.setattr(service,'store',cs);monkeypatch.setattr(service,'runtime',rt);monkeypatch.setattr(config,'MODEL_AGENT_DIR',tmp_path/'models');service.cancellations.clear()
    return bs,pr,cs,rt,TestClient(app),db


def _binding(bs,name='mock-a',model='mock-v1',**kw):return bs.create(LLMBindingInput(display_name=name,provider='MOCK',model=model,is_default=kw.pop('is_default',False),**kw))


def test_binding_create(llm_env):assert _binding(llm_env[0])['binding_id'].startswith('B_')
def test_binding_no_plaintext_secret(llm_env):
    bs,_,_,_,_,db=llm_env;secret='unit-test-secret-value';bs.create(LLMBindingInput(display_name='openai',provider='OPENAI',model='gpt-test',api_key=secret));assert secret.encode() not in db.read_bytes()
def test_binding_plaintext_response_for_local_workbench(llm_env):
    secret='unit-test-value-abcd';row=llm_env[0].create(LLMBindingInput(display_name='openai',provider='OPENAI',model='gpt-test',api_key=secret));assert row['api_key_plaintext']==secret and row['api_key_masked']==secret
def test_connection_success(llm_env):
    bs=llm_env[0];row=_binding(bs);assert llm_env[3].test_connection(row['binding_id'])['status']=='CONNECTED'
def test_connection_auth_fail(llm_env):
    bs=llm_env[0];row=_binding(bs,model='mock-auth-fail')
    with pytest.raises(AuthError):llm_env[3].test_connection(row['binding_id'])
def test_mock_provider_chat():assert MockProvider().chat([{'role':'user','content':'hello'}])['execution_mode']=='MOCK'
def test_mock_stream():assert ''.join(MockProvider().stream_chat([{'role':'user','content':'hello'}])).startswith('MOCK:')
def test_llm_runtime(llm_env):
    row=_binding(llm_env[0]);result=llm_env[3].chat('GENERAL_CHAT',[{'role':'user','content':'hello'}],row['binding_id']);assert result['binding']['binding_id']==row['binding_id']
def test_prompt_version(llm_env):assert llm_env[1].get('SEMANTIC_ANALYSIS')['prompt_id']=='semantic_v1'
def test_conversation_create(llm_env):assert llm_env[2].create_conversation()['conversation_id'].startswith('C_')
def test_message_persistence(llm_env):
    cs=llm_env[2];c=cs.create_conversation();cs.add_message(conversation_id=c['conversation_id'],role='user',content='x',status='SUCCESS');assert cs.conversation(c['conversation_id'])['messages'][0]['content']=='x'
def test_structured_semantic_output(llm_env):
    row=_binding(llm_env[0]);result=llm_env[3].chat('SEMANTIC_ANALYSIS',[{'role':'user','content':'analyze'}],row['binding_id']);assert result['structured']['risk_domain']=='APPLICATION_BEHAVIOR'
def test_structured_invalid_json(llm_env):
    row=_binding(llm_env[0]);result=llm_env[3].chat('SEMANTIC_ANALYSIS',[{'role':'user','content':'[MOCK_INVALID_JSON]'}],row['binding_id']);assert result['repair_attempted'] is True and result['structured']
def test_json_repair(llm_env):test_structured_invalid_json(llm_env)
def test_no_binding_no_fake_response(llm_env):
    with pytest.raises(NoActiveBinding):llm_env[3].chat('GENERAL_CHAT',[{'role':'user','content':'hello'}])
def test_provider_timeout(llm_env):
    row=_binding(llm_env[0],model='mock-timeout')
    with pytest.raises(ProviderTimeout):llm_env[3].chat('GENERAL_CHAT',[{'role':'user','content':'x'}],row['binding_id'])
def test_provider_rate_limit(llm_env):
    row=_binding(llm_env[0],model='mock-rate-limit')
    with pytest.raises(RateLimitError):llm_env[3].chat('GENERAL_CHAT',[{'role':'user','content':'x'}],row['binding_id'])
def test_fallback_audit(llm_env):
    bs=llm_env[0];fallback=_binding(bs,'fallback');primary=_binding(bs,'primary','mock-auth-fail',fallback_binding_id=fallback['binding_id']);result=llm_env[3].chat('GENERAL_CHAT',[{'role':'user','content':'x'}],primary['binding_id']);assert result['fallback_used'] and result['binding']['binding_id']==fallback['binding_id'] and 'Primary' in result['router_decision_reason']


def _api_setup(env):
    bs,_,_,_,client,_=env;a=_binding(bs,'binding-a',is_default=True);b=_binding(bs,'binding-b');c=client.post('/api/agent-chat/conversations',json={'title':'Test','agent_type':'GENERAL_CHAT','default_binding_id':a['binding_id']}).json();return client,a,b,c
def test_stream_message(llm_env):
    client,a,_,c=_api_setup(llm_env)
    with client.stream('POST',f"/api/agent-chat/conversations/{c['conversation_id']}/messages/stream",json={'content':'stream me','binding_id':a['binding_id']}) as response:text=''.join(response.iter_text())
    assert response.status_code==200 and 'event: delta' in text and 'event: done' in text
def test_switch_binding(llm_env):
    client,a,b,c=_api_setup(llm_env);cid=c['conversation_id'];client.post(f'/api/agent-chat/conversations/{cid}/messages',json={'content':'one','binding_id':a['binding_id']});client.post(f'/api/agent-chat/conversations/{cid}/messages',json={'content':'two','binding_id':b['binding_id']});traces=client.get('/api/agent-chat/calls',params={'conversation_id':cid}).json();assert {x['binding_id'] for x in traces}=={a['binding_id'],b['binding_id']}
def test_agent_mode_switch(llm_env):
    client,a,_,c=_api_setup(llm_env);cid=c['conversation_id'];client.post(f'/api/agent-chat/conversations/{cid}/messages',json={'content':'semantic','agent_type':'SEMANTIC_ANALYSIS','binding_id':a['binding_id']});client.post(f'/api/agent-chat/conversations/{cid}/messages',json={'content':'hypothesis','agent_type':'HYPOTHESIS','binding_id':a['binding_id']});messages=client.get(f'/api/agent-chat/conversations/{cid}').json()['messages'];assistant=[x for x in messages if x['role']=='assistant'];assert [x['prompt_version'] for x in assistant]==['semantic_v1','hypothesis_v1']
def test_llm_audit(llm_env):
    client,a,_,c=_api_setup(llm_env);client.post(f"/api/agent-chat/conversations/{c['conversation_id']}/messages",json={'content':'hello','binding_id':a['binding_id']});call=client.get('/api/agent-chat/calls').json()[0];assert call['call_id'] and call['execution_mode']=='MOCK' and call['input_context_hash']
def test_trace(llm_env):test_llm_audit(llm_env)
def test_proposal_create(llm_env):
    client,a,_,c=_api_setup(llm_env);client.post(f"/api/agent-chat/conversations/{c['conversation_id']}/messages",json={'content':'idea','agent_type':'HYPOTHESIS','binding_id':a['binding_id']});assert len(client.get('/api/agent-chat/proposals').json())==2
def test_proposal_accept(llm_env):
    client,a,_,c=_api_setup(llm_env);client.patch(f"/api/agent-chat/conversations/{c['conversation_id']}",json={'dataset_id':'dataset-x'});client.post(f"/api/agent-chat/conversations/{c['conversation_id']}/messages",json={'content':'idea','agent_type':'HYPOTHESIS','binding_id':a['binding_id']});p=next(x for x in client.get('/api/agent-chat/proposals').json() if x['proposal_type']=='FEATURE_CANDIDATE');result=client.post(f"/api/agent-chat/proposals/{p['proposal_id']}/accept").json();assert result['status']=='EXECUTED' and result['registry_object_id']
def test_proposal_reject(llm_env):
    client,a,_,c=_api_setup(llm_env);client.post(f"/api/agent-chat/conversations/{c['conversation_id']}/messages",json={'content':'idea','agent_type':'HYPOTHESIS','binding_id':a['binding_id']});p=client.get('/api/agent-chat/proposals').json()[0];assert client.post(f"/api/agent-chat/proposals/{p['proposal_id']}/reject").json()['status']=='REJECTED'
