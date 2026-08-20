from __future__ import annotations
import json,os,threading,time,uuid
from pathlib import Path
from typing import Any,Iterator

from core.llm.bindings import BindingStore
from core.llm.context import AgentContextBuilder
from core.llm.exceptions import LLMError
from core.llm.prompts import PromptRegistry
from core.llm.runtime import LLMRuntime
from core.llm.storage import ChatStore
from core.model_agent.registry import FeatureRegistry,HypothesisRegistry
from core.model_agent.registry import utc_now
from .. import config
from .analysis_service import DATASETS

DB_PATH=config.RUNTIME_DIR/'agent_chat.sqlite3'; bindings=BindingStore(DB_PATH);prompts=PromptRegistry(DB_PATH);store=ChatStore(DB_PATH);runtime=LLMRuntime(bindings,prompts);builder=AgentContextBuilder(int(os.getenv('MAX_CONTEXT_ITEMS','30')),int(os.getenv('MAX_CONTEXT_CHARS','12000')));cancellations:dict[str,threading.Event]={}

def _source(conversation):
    did=conversation.get('dataset_id');source={}
    if not did or did not in DATASETS:return source
    ds=DATASETS[did];df=ds['df'];source['dataset_summary']={'rows':len(df),'columns':len(df.columns),'fields':[{'field':c,'dtype':str(df[c].dtype),'missing_rate':float(df[c].isna().mean()),'unique_count':int(df[c].nunique(dropna=True)),'sample_values':[str(x)[:100] for x in df[c].dropna().head(3)]} for c in df.columns[:30]]}
    source['rule_groups']=ds.get('state',{}).get('stages',{}).get('rule_groups',{}).get('summaries',[])[:20]
    root=config.MODEL_AGENT_DIR/did
    for key,file in [('semantic','semantic_state.json'),('hypotheses','hypothesis_registry.json'),('features','feature_registry.json'),('experiments','experiment_registry.json'),('diagnoses','diagnosis_registry.json'),('model_state','model_agent_state.json')]:
        path=root/file
        if path.exists():
            try:source[key]=json.loads(path.read_text(encoding='utf-8'))
            except ValueError:pass
    return source

def _context(conversation,agent_type,attachments):return builder.build(agent_type,conversation,attachments,_source(conversation))
def _tools(ctx):
    mapping={'dataset_summary':'get_dataset_summary','variable_profiles':'get_variable_profile','rule_groups':'get_rule_groups','features':'get_feature_registry','hypotheses':'get_hypothesis_registry','experiments':'get_experiment_history','model_state':'get_model_state','evaluation':'get_evaluation_summary'}
    return [{'tool_name':mapping[x],'arguments_summary':{'dataset_id':ctx['summary'].get('dataset_id')},'result_summary':{'included_in_context':True},'latency_ms':0} for x in ctx['summary'].get('included_sections',[]) if x in mapping]
def _history(cid):return [{'role':x['role'],'content':x['content']} for x in store.messages(cid) if x['role'] in ('user','assistant') and x['status'] in ('SUCCESS','CANCELLED')]
def _error(exc):return getattr(exc,'code','PROVIDER_ERROR'),str(exc)[:300]
def _proposal(agent_type,conversation,message,structured):
    if not structured:return []
    mapping={'SEMANTIC_ANALYSIS':'SEMANTIC_UPDATE','HYPOTHESIS':'HYPOTHESIS_CREATE','PLANNER':'EXPERIMENT_SUGGESTION','DIAGNOSIS':'DIAGNOSIS_ACTION'};ptype=mapping.get(agent_type)
    if not ptype:return []
    p=store.add_proposal(conversation_id=conversation['conversation_id'],message_id=message['message_id'],proposal_type=ptype,title=structured.get('hypothesis') or structured.get('field') or structured.get('next_action') or structured.get('diagnosis_type'),payload=structured,reason=structured.get('reason') or structured.get('risk_mechanism') or structured.get('recommended_action',''),requires_human=True);rows=[p]
    if agent_type=='HYPOTHESIS':
        for feature in structured.get('candidate_feature_ideas',[])[:5]:rows.append(store.add_proposal(conversation_id=conversation['conversation_id'],message_id=message['message_id'],proposal_type='FEATURE_CANDIDATE',title=feature.get('feature_name','Feature candidate'),payload=feature,reason=structured.get('risk_mechanism',''),requires_human=True))
    return rows
def _audit(conversation,message,agent_type,binding,prompt,ctx,started,success,error=None,router_reason=None,usage=None,execution_mode=None):
    code,summary=_error(error) if error else (None,None);usage=usage or {}
    return store.add_call(conversation_id=conversation['conversation_id'],message_id=message['message_id'],agent_type=agent_type,provider=binding.get('provider') if binding else None,binding_id=binding.get('binding_id') if binding else None,model=binding.get('model') if binding else None,prompt_version=prompt.get('prompt_id') if prompt else None,input_context_hash=ctx['hash'],context_summary=ctx['summary'],latency_ms=round((time.perf_counter()-started)*1000),prompt_tokens=usage.get('prompt_tokens'),completion_tokens=usage.get('completion_tokens'),total_tokens=usage.get('total_tokens'),success=success,error_type=code,error_summary=summary,state_id=conversation.get('state_id'),experiment_id=conversation.get('experiment_id'),router_decision_reason=router_reason,execution_mode=execution_mode)

def send(cid,content,agent_type=None,binding_id=None,attachments=None,parent_message_id=None):
    conv=store.conversation(cid);agent_type=agent_type or conv['agent_type'];binding_id=binding_id or conv.get('default_binding_id');attachments=attachments or [];store.update_conversation(cid,{'agent_type':agent_type,'default_binding_id':binding_id})
    user=store.add_message(conversation_id=cid,role='user',content=content,attachments=attachments,agent_type=agent_type,status='SUCCESS',parent_message_id=parent_message_id);assistant=store.add_message(conversation_id=cid,role='assistant',agent_type=agent_type,status='PENDING',parent_message_id=parent_message_id);ctx=_context(conv,agent_type,attachments);started=time.perf_counter();binding=prompt=None
    try:
        result=runtime.chat(agent_type,_history(cid),binding_id,ctx['text']);binding=result['binding'];prompt=result['prompt'];response=result['result'];usage=response.get('usage',{});proposals=_proposal(agent_type,conv,assistant,result['structured']);call=_audit(conv,assistant,agent_type,binding,prompt,ctx,started,True,router_reason=result['router_decision_reason'],usage=usage,execution_mode=response.get('execution_mode'));assistant=store.update_message(assistant['message_id'],{'content':response['content'],'binding_id':binding['binding_id'],'provider':binding['provider'],'model':response.get('model',binding['model']),'prompt_version':prompt['prompt_id'],'tool_calls':_tools(ctx),'proposal_ids':[p['proposal_id'] for p in proposals],'latency_ms':call['latency_ms'],'prompt_tokens':usage.get('prompt_tokens'),'completion_tokens':usage.get('completion_tokens'),'total_tokens':usage.get('total_tokens'),'status':'SUCCESS','execution_mode':response.get('execution_mode')});return {'user_message':user,'assistant_message':assistant,'proposals':proposals,'trace':call,'structured':result['structured']}
    except Exception as exc:
        call=_audit(conv,assistant,agent_type,binding,prompt,ctx,started,False,error=exc);assistant=store.update_message(assistant['message_id'],{'status':'FAILED','error':f"{call['error_type']}: {call['error_summary']}"});raise

def stream(cid,content,agent_type=None,binding_id=None,attachments=None,parent_message_id=None)->Iterator[str]:
    conv=store.conversation(cid);agent_type=agent_type or conv['agent_type'];binding_id=binding_id or conv.get('default_binding_id');attachments=attachments or [];store.update_conversation(cid,{'agent_type':agent_type,'default_binding_id':binding_id});user=store.add_message(conversation_id=cid,role='user',content=content,attachments=attachments,agent_type=agent_type,status='SUCCESS',parent_message_id=parent_message_id);assistant=store.add_message(conversation_id=cid,role='assistant',agent_type=agent_type,status='STREAMING',parent_message_id=parent_message_id);event=threading.Event();cancellations[assistant['message_id']]=event;ctx=_context(conv,agent_type,attachments);started=time.perf_counter();chunks=[];meta=None
    yield _sse('start',{'user_message':user,'assistant_message':assistant})
    try:
        for chunk,meta in runtime.stream(agent_type,_history(cid),binding_id,ctx['text']):
            if event.is_set():
                saved=store.update_message(assistant['message_id'],{'content':''.join(chunks),'status':'CANCELLED'});yield _sse('cancelled',{'message':saved});return
            chunks.append(chunk);yield _sse('delta',{'message_id':assistant['message_id'],'content':chunk})
        binding=meta['binding'];prompt=meta['prompt'];response=meta['result'];usage=response.get('usage',{});structured=None
        if agent_type!='GENERAL_CHAT':
            try:structured=json.loads(''.join(chunks))
            except ValueError:structured=None
        proposals=_proposal(agent_type,conv,assistant,structured);call=_audit(conv,assistant,agent_type,binding,prompt,ctx,started,True,router_reason=meta['router_decision_reason'],usage=usage,execution_mode=response.get('execution_mode'));saved=store.update_message(assistant['message_id'],{'content':''.join(chunks),'binding_id':binding['binding_id'],'provider':binding['provider'],'model':binding['model'],'prompt_version':prompt['prompt_id'],'tool_calls':_tools(ctx),'proposal_ids':[p['proposal_id'] for p in proposals],'latency_ms':call['latency_ms'],'status':'SUCCESS','execution_mode':response.get('execution_mode')});yield _sse('done',{'message':saved,'proposals':proposals,'trace':call})
    except Exception as exc:
        call=_audit(conv,assistant,agent_type,None,None,ctx,started,False,error=exc);saved=store.update_message(assistant['message_id'],{'content':''.join(chunks),'status':'FAILED','error':f"{call['error_type']}: {call['error_summary']}"});yield _sse('error',{'message':saved,'trace':call})
    finally:cancellations.pop(assistant['message_id'],None)
def _sse(event,data):return f"event: {event}\ndata: {json.dumps(data,ensure_ascii=False)}\n\n"
def cancel(mid):
    if mid in cancellations:cancellations[mid].set();return True
    return False

def decide_proposal(pid,accept):
    proposal=store.proposal(pid)
    if proposal['status']!='PENDING':raise ValueError('Proposal already decided')
    if not accept:return store.update_proposal(pid,'REJECTED')
    conv=store.conversation(proposal['conversation_id']);did=conv.get('dataset_id');object_id=None
    if did and proposal['proposal_type']=='HYPOTHESIS_CREATE':
        payload=proposal['payload'];object_id=f"H_LLM_{uuid.uuid4().hex[:10]}";HypothesisRegistry(config.MODEL_AGENT_DIR/did).add({'hypothesis_id':object_id,'evidence_type':'LLM_PROPOSAL','evidence':payload.get('evidence'),'risk_mechanism':payload.get('risk_mechanism'),'source_fields':[],'candidate_features':payload.get('candidate_feature_ideas',[]),'expected_direction':payload.get('expected_direction'),'expected_benefit':'LLM proposal pending experiment','confidence':payload.get('confidence'),'estimated_cost':payload.get('cost'),'status':'PROPOSED','related_experiments':[],'source_message_id':proposal['message_id']})
    elif did and proposal['proposal_type']=='FEATURE_CANDIDATE':
        payload=proposal['payload'];object_id=f"F_LLM_{uuid.uuid4().hex[:10]}";FeatureRegistry(config.MODEL_AGENT_DIR/did).add({'feature_id':object_id,'feature_name':payload.get('feature_name'),'feature_version':'1.0','feature_type':payload.get('feature_type','RAW'),'source_fields':payload.get('source_fields',[]),'source_feature_ids':[],'semantic_domain':'LLM_PROPOSAL','formula':payload.get('formula',payload.get('feature_name')),'calculation_description':proposal['reason'],'generation_reason':proposal['reason'],'hypothesis_id':None,'experiment_id':None,'expected_direction':None,'status':'GENERATED','validation_result':None,'lr_eligible':False,'lgbm_eligible':False,'approved':False,'source_message_id':proposal['message_id']})
    status='EXECUTED' if object_id else 'ACCEPTED';return store.update_proposal(pid,status,object_id)

def binding_views():
    calls=store.calls({});rows=[]
    for binding in bindings.all():
        own=[x for x in calls if x.get('binding_id')==binding['binding_id']];success=[x for x in own if x.get('success')];binding['usage']={'calls':len(own),'success_rate':len(success)/len(own) if own else None,'avg_latency_ms':round(sum(x.get('latency_ms') or 0 for x in own)/len(own)) if own else None,'total_tokens':sum(x.get('total_tokens') or 0 for x in own),'last_used':own[0]['created_at'] if own else None};rows.append(binding)
    return rows
