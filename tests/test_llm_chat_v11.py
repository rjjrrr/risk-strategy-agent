import json,sqlite3
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app import config
from backend.app.main import app
from backend.app.services import agent_chat_service as service
from core.llm.bindings import BindingStore
from core.llm.exceptions import AuthError,NoActiveBinding,ProviderTimeout,RateLimitError
from core.llm.prompts import PromptRegistry
from core.llm.provider import MockProvider
from core.llm.runtime import LLMRuntime,_repair_message
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
def test_binding_secret_is_masked(llm_env):
    secret='unit-test-value-abcd';row=llm_env[0].create(LLMBindingInput(display_name='openai',provider='OPENAI',model='gpt-test',api_key=secret));assert 'api_key_plaintext' not in row and row['api_key_masked']!=secret and row['api_key_masked'].endswith('abcd')
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
def test_phase1_prompt_versions(llm_env):assert [llm_env[1].get(x)['prompt_id'] for x in ('GENERAL_CHAT','ANALYSIS_AGENT','DECISION_AGENT')]==['general_v1','analysis_agent_v1','decision_agent_v1']
def test_source_prompt_wins_over_stale_database_version(llm_env):
    _,pr,_,_,_,db=llm_env
    with sqlite3.connect(db) as con:con.execute("INSERT INTO prompt_versions VALUES(?,?,?,?,?,?,1)",('analysis_agent_v99','ANALYSIS_AGENT','v99','stale prompt','structured','2099-01-01'))
    assert pr.get('ANALYSIS_AGENT')['prompt_id']=='analysis_agent_v1'
def test_repair_message_contains_schema_and_validation_issue():
    message=_repair_message('ANALYSIS_AGENT',ValueError('truncated JSON'))
    assert 'Required JSON Schema' in message and 'analysis_summary' in message and 'truncated JSON' in message
def test_conversation_create(llm_env):assert llm_env[2].create_conversation()['conversation_id'].startswith('C_')
def test_message_persistence(llm_env):
    cs=llm_env[2];c=cs.create_conversation();cs.add_message(conversation_id=c['conversation_id'],role='user',content='x',status='SUCCESS');assert cs.conversation(c['conversation_id'])['messages'][0]['content']=='x'
def test_structured_semantic_output(llm_env):
    row=_binding(llm_env[0]);result=llm_env[3].chat('SEMANTIC_ANALYSIS',[{'role':'user','content':'analyze'}],row['binding_id']);assert result['structured']['risk_domain']=='APPLICATION_BEHAVIOR'
def test_structured_invalid_json(llm_env):
    row=_binding(llm_env[0]);result=llm_env[3].chat('SEMANTIC_ANALYSIS',[{'role':'user','content':'[MOCK_INVALID_JSON]'}],row['binding_id']);assert result['repair_attempted'] is True and result['structured']
def test_json_repair(llm_env):test_structured_invalid_json(llm_env)
def test_no_binding_no_mock_fallback(llm_env):
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
def test_general_chat_cannot_claim_execution(llm_env):
    client,a,_,c=_api_setup(llm_env);cid=c['conversation_id']
    result=client.post(f'/api/agent-chat/conversations/{cid}/messages',json={'content':'随机挖掘，马上开始','binding_id':a['binding_id']}).json()
    assert result['assistant_message']['runtime_type']=='DETERMINISTIC'
    assert '未执行任何挖掘或实验' in result['assistant_message']['content']
    assert result['assistant_message']['tool_calls']==[] and result['proposals']==[]
def test_general_chat_execution_guard_applies_to_stream(llm_env):
    client,a,_,c=_api_setup(llm_env)
    with client.stream('POST',f"/api/agent-chat/conversations/{c['conversation_id']}/messages/stream",json={'content':'开始运行特征实验','binding_id':a['binding_id']}) as response:text=''.join(response.iter_text())
    assert response.status_code==200 and '未执行任何挖掘或实验' in text and 'event: done' in text
def test_switch_binding_history(llm_env):
    client,a,b,c=_api_setup(llm_env);cid=c['conversation_id'];client.post(f'/api/agent-chat/conversations/{cid}/messages',json={'content':'one','binding_id':a['binding_id']});client.post(f'/api/agent-chat/conversations/{cid}/messages',json={'content':'two','binding_id':b['binding_id']});traces=client.get('/api/agent-chat/calls',params={'conversation_id':cid}).json();messages=client.get(f'/api/agent-chat/conversations/{cid}').json()['messages'];assistant=[x for x in messages if x['role']=='assistant'];assert {x['binding_id'] for x in traces}=={a['binding_id'],b['binding_id']} and [x['binding_id'] for x in assistant]==[a['binding_id'],b['binding_id']]
def test_switch_agent_history(llm_env):
    client,a,_,c=_api_setup(llm_env);cid=c['conversation_id'];modes=[('GENERAL_CHAT','general'),('ANALYSIS_AGENT','analysis'),('DECISION_AGENT','decision')]
    for mode,text in modes:client.post(f'/api/agent-chat/conversations/{cid}/messages',json={'content':text,'agent_type':mode,'binding_id':a['binding_id']})
    messages=client.get(f'/api/agent-chat/conversations/{cid}').json()['messages'];assistant=[x for x in messages if x['role']=='assistant'];assert [x['agent_type'] for x in assistant]==[x[0] for x in modes] and [x['prompt_version'] for x in assistant]==['general_v1','analysis_agent_v1','decision_agent_v1']
def test_llm_audit(llm_env):
    client,a,_,c=_api_setup(llm_env);client.post(f"/api/agent-chat/conversations/{c['conversation_id']}/messages",json={'content':'hello','binding_id':a['binding_id']});call=client.get('/api/agent-chat/calls').json()[0];required={'call_id','conversation_id','message_id','agent_type','runtime_type','binding_id','provider','model','prompt_version','latency_ms','prompt_tokens','completion_tokens','total_tokens','success','error_type','error_summary','created_at'};assert required<=set(call) and call['runtime_type']=='MOCK' and call['input_context_hash'] and 'api_key' not in json.dumps(call)
def test_trace(llm_env):test_llm_audit(llm_env)
def test_message_runtime_type(llm_env):
    client,a,_,c=_api_setup(llm_env);result=client.post(f"/api/agent-chat/conversations/{c['conversation_id']}/messages",json={'content':'hello','binding_id':a['binding_id']}).json();assert result['assistant_message']['runtime_type']=='MOCK' and result['trace']['runtime_type']=='MOCK'
def test_trace_metadata(llm_env):
    client,a,_,c=_api_setup(llm_env);result=client.post(f"/api/agent-chat/conversations/{c['conversation_id']}/messages",json={'content':'hello','binding_id':a['binding_id']}).json();trace=result['trace'];assert trace['message_id']==result['assistant_message']['message_id'] and trace['conversation_id']==c['conversation_id'] and trace['binding_id']==a['binding_id'] and trace['prompt_version']=='general_v1' and trace['latency_ms']>=0
def test_cancel_stream(llm_env):
    client,a,_,c=_api_setup(llm_env);gen=service.stream(c['conversation_id'],'cancel me',binding_id=a['binding_id']);start=next(gen);mid=json.loads(start.split('data: ',1)[1])['assistant_message']['message_id'];assert 'event: delta' in next(gen);assert service.cancel(mid);cancelled=next(gen);message=service.store.conversation(c['conversation_id'])['messages'][-1];call=service.store.calls({'conversation_id':c['conversation_id']})[0];assert 'event: cancelled' in cancelled and message['status']=='CANCELLED' and message['content'] and call['error_type']=='CANCELLED'
def test_retry_message(llm_env):
    client,a,_,c=_api_setup(llm_env);cid=c['conversation_id'];first=client.post(f'/api/agent-chat/conversations/{cid}/messages',json={'content':'one','binding_id':a['binding_id']}).json()['assistant_message'];result=client.post(f"/api/agent-chat/conversations/{cid}/messages/{first['message_id']}/retry",json={'content':'one','binding_id':a['binding_id']});messages=client.get(f'/api/agent-chat/conversations/{cid}').json()['messages'];assistant=[x for x in messages if x['role']=='assistant'];assert result.status_code==200 and len(assistant)==2 and assistant[0]['message_id']==first['message_id'] and assistant[1]['parent_message_id']==first['message_id']
def test_api_error_rendering(llm_env):
    bs,_,_,_,client,_=llm_env;bad=_binding(bs,'bad','mock-auth-fail',is_default=True);c=client.post('/api/agent-chat/conversations',json={'default_binding_id':bad['binding_id']}).json();response=client.post(f"/api/agent-chat/conversations/{c['conversation_id']}/messages",json={'content':'hello','binding_id':bad['binding_id']});messages=client.get(f"/api/agent-chat/conversations/{c['conversation_id']}").json()['messages'];source=(Path(__file__).parents[1]/'frontend/src/pages/AgentChatPage.tsx').read_text(encoding='utf-8');assert response.status_code==503 and messages[-1]['status']=='FAILED' and messages[-1]['runtime_type']=='MOCK' and all(code in source for code in ('AUTH_ERROR','RATE_LIMIT','TIMEOUT','CONNECTION_ERROR','MODEL_NOT_FOUND','PROVIDER_ERROR'))
def test_chat_scroll_layout():
    root=Path(__file__).parents[1];css=(root/'frontend/src/agent-chat.css').read_text(encoding='utf-8');page=(root/'frontend/src/pages/AgentChatPage.tsx').read_text(encoding='utf-8');assert '.chat-main{position:relative;display:flex' in css and '.chat-messages{flex:1 1 auto;min-height:0;overflow-y:auto' in css and '.composer-area{flex:0 0 auto' in css and '.conversation-scroll{min-height:0;flex:1;overflow-y:auto' in css and '.chat-drawer{position:fixed' in css and 'overscroll-behavior:contain' in css and 'scrollHeight-el.scrollTop-el.clientHeight<=120' in page and 'if(nearBottom.current)' in page and 'Back to bottom' in page and 'streamConversation===chat?.conversation_id' in page and 'scrollIntoView' not in page
def test_proposal_create(llm_env):
    client,a,_,c=_api_setup(llm_env);client.post(f"/api/agent-chat/conversations/{c['conversation_id']}/messages",json={'content':'idea','agent_type':'HYPOTHESIS','binding_id':a['binding_id']});assert len(client.get('/api/agent-chat/proposals').json())==2
def test_proposal_accept(llm_env):
    client,a,_,c=_api_setup(llm_env);service.DATASETS['dataset-x']={'df':pd.DataFrame({'query_cnt_7d':[1,2],'query_cnt_90d':[2,4]})};client.patch(f"/api/agent-chat/conversations/{c['conversation_id']}",json={'dataset_id':'dataset-x'});client.post(f"/api/agent-chat/conversations/{c['conversation_id']}/messages",json={'content':'idea','agent_type':'HYPOTHESIS','binding_id':a['binding_id']});p=next(x for x in client.get('/api/agent-chat/proposals').json() if x['proposal_type']=='FEATURE_CANDIDATE');result=client.post(f"/api/agent-chat/proposals/{p['proposal_id']}/accept").json();specs=client.get('/api/feature-specs',params={'dataset_id':'dataset-x'}).json();assert result['status']=='SAVED' and result['registry_object_id'].startswith('FS_') and len(specs)==1 and specs[0]['proposal_id']==p['proposal_id']

def test_saved_feature_proposal_is_idempotent(llm_env):
    client,a,_,c=_api_setup(llm_env);service.DATASETS['dataset-x']={'df':pd.DataFrame({'query_cnt_7d':[1,2],'query_cnt_90d':[2,4]})};client.patch(f"/api/agent-chat/conversations/{c['conversation_id']}",json={'dataset_id':'dataset-x'});client.post(f"/api/agent-chat/conversations/{c['conversation_id']}/messages",json={'content':'idea','agent_type':'HYPOTHESIS','binding_id':a['binding_id']});p=next(x for x in client.get('/api/agent-chat/proposals').json() if x['proposal_type']=='FEATURE_CANDIDATE');accepted=client.post(f"/api/agent-chat/proposals/{p['proposal_id']}/accept").json();again=client.post(f"/api/feature-specs/from-proposal/{p['proposal_id']}",json={'dataset_id':'dataset-x'}).json();assert accepted['registry_object_id']==again['feature_spec_id'] and len(client.get('/api/feature-specs',params={'dataset_id':'dataset-x'}).json())==1
def test_proposal_reject(llm_env):
    client,a,_,c=_api_setup(llm_env);client.post(f"/api/agent-chat/conversations/{c['conversation_id']}/messages",json={'content':'idea','agent_type':'HYPOTHESIS','binding_id':a['binding_id']});p=client.get('/api/agent-chat/proposals').json()[0];assert client.post(f"/api/agent-chat/proposals/{p['proposal_id']}/reject").json()['status']=='REJECTED'
