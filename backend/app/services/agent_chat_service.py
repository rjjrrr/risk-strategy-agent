from __future__ import annotations

import json, os, threading, time, uuid
from typing import Any, Iterator

from core.context import ContextRequest
from core.llm.bindings import BindingStore
from core.llm.context import AgentContextBuilder
from core.llm.prompts import PromptRegistry
from core.llm.runtime import LLMRuntime
from core.llm.storage import ChatStore
from core.model_agent.registry import FeatureRegistry, HypothesisRegistry
from .. import config
from .analysis_service import DATASETS
from . import context_service

DB_PATH=config.RUNTIME_DIR/'agent_chat.sqlite3'; bindings=BindingStore(DB_PATH); prompts=PromptRegistry(DB_PATH); store=ChatStore(DB_PATH); runtime=LLMRuntime(bindings,prompts)
legacy_builder=AgentContextBuilder(int(os.getenv('MAX_CONTEXT_ITEMS','30')),int(os.getenv('MAX_CONTEXT_CHARS','12000'))); cancellations:dict[str,threading.Event]={}

def _legacy_source(conversation):
    did=conversation.get('dataset_id'); source={}
    if did and did in DATASETS:
        df=DATASETS[did]['df']; source['dataset_summary']={'rows':len(df),'columns':len(df.columns),'fields':[{'field':c,'dtype':str(df[c].dtype),'missing_rate':float(df[c].isna().mean()),'unique_count':int(df[c].nunique(dropna=True))} for c in df.columns[:30]]}
        source['rule_groups']=DATASETS[did].get('state',{}).get('stages',{}).get('rule_groups',{}).get('summaries',[])[:20]
    return source

def _context(conversation,agent_type,attachments,user_query,context_options=None,focus_fields=None):
    did=conversation.get('dataset_id')
    if agent_type!='ANALYSIS_AGENT' or not did or did not in DATASETS:return legacy_builder.build(agent_type,conversation,attachments,_legacy_source(conversation))
    options={k:v for k,v in (context_options or {}).items() if k in ContextRequest.model_fields}
    req=ContextRequest(conversation_id=conversation['conversation_id'],dataset_id=did,user_query=user_query,agent_type=agent_type,focus_fields=focus_fields or [],**options)
    b=context_service.build(req,store); summary={'dataset_id':did,'attachment_count':len(attachments),'included_sections':b.sources_used,'context_id':b.context_id,'context_hash':b.context_hash,'context_items_count':b.included_items,'estimated_context_tokens':b.estimated_context_tokens,'sources_used':b.sources_used,'source_counts':b.source_counts,'dropped_items':b.dropped_items,'deduplicated_items':b.deduplicated_items,'versions':b.versions,'cache_hit':b.cache_hit}
    return {'text':b.text,'hash':b.context_hash,'context_id':b.context_id,'summary':summary}

def _tools(ctx):
    mapping={'DATASET_SUMMARY':'get_dataset_summary','DATA_HEALTH':'get_data_health','GOVERNANCE':'get_governance','VARIABLE_PROFILE':'get_variable_profile','RULE_SUMMARY':'get_rule_summary','RULE_GROUP':'get_rule_groups','FEATURE_REGISTRY':'get_feature_registry','HYPOTHESIS_REGISTRY':'get_hypothesis_registry','EXPERIMENT_HISTORY':'get_experiment_history','MODEL_STATE':'get_model_state','CONVERSATION_MEMORY':'get_conversation_memory','dataset_summary':'get_dataset_summary','rule_groups':'get_rule_groups'}
    return [{'tool_name':mapping[x],'arguments_summary':{'dataset_id':ctx['summary'].get('dataset_id')},'result_summary':{'included_in_context':True},'latency_ms':0} for x in ctx['summary'].get('included_sections',[]) if x in mapping]

def _history(cid,limit=8):
    rows=[{'role':x['role'],'content':x['content']} for x in store.messages(cid) if x['role'] in ('user','assistant') and x['status'] in ('SUCCESS','CANCELLED')]
    return rows[-limit:]
def _error(exc):return getattr(exc,'code','PROVIDER_ERROR'),str(exc)[:300]

def _governance(dataset_id):
    rows=DATASETS.get(dataset_id,{}).get('governance')
    if rows is None:return {}
    records=rows.to_dict('records') if hasattr(rows,'to_dict') else rows
    return {str(x.get('field')):x for x in records}

def _feature_validation(dataset_id,p):
    ds=DATASETS.get(dataset_id,{}); df=ds.get('df'); schema={str(x) for x in df.columns} if hasattr(df,'columns') else set(); registry=FeatureRegistry(config.MODEL_AGENT_DIR/dataset_id); existing=registry.all(); names={str(x.get('feature_name')) for x in existing}|{str(x.get('feature_id')) for x in existing}; fields=[str(x) for x in p.get('source_fields',[])]
    missing=[x for x in fields if x not in schema and x not in names]
    if missing:return {'validation_status':'INVALID','validation_code':'INVALID_SOURCE_FIELD','invalid_fields':missing}
    signature=(str(p.get('feature_name','')).strip().lower(),tuple(sorted(fields)),str(p.get('formula','')).replace(' ','').lower(),str(p.get('semantic_meaning','')).strip().lower())
    for row in existing:
        other=(str(row.get('feature_name','')).strip().lower(),tuple(sorted(str(x) for x in row.get('source_fields',[]))),str(row.get('formula','')).replace(' ','').lower(),str(row.get('semantic_meaning') or row.get('calculation_description','')).strip().lower())
        if signature==other or (signature[1]==other[1] and signature[2]==other[2]):return {'validation_status':'DUPLICATE','validation_code':'DUPLICATE_FEATURE','existing_feature_id':row.get('feature_id')}
    gov=_governance(dataset_id); risky=[x for x in fields if gov.get(x,{}).get('decision')=='SUSPECT_LEAKAGE' or gov.get(x,{}).get('semantic_type') in {'TARGET_LEAKAGE','POST_LOAN_FEATURE','SUSPECT_LEAKAGE'}]
    if risky:return {'validation_status':'LEAKAGE_RISK','validation_code':'LEAKAGE_RISK','risk_fields':risky}
    dates=[x for x in fields if gov.get(x,{}).get('semantic_type')=='DATETIME']
    if dates and str(p.get('feature_type','')).upper()=='RAW':return {'validation_status':'REVIEW','validation_code':'DATETIME_RAW_FORBIDDEN','risk_fields':dates}
    return {'validation_status':p.get('status','REVIEW'),'validation_code':'VALIDATED'}

def _hypothesis_validation(dataset_id,p):
    ds=DATASETS.get(dataset_id,{}); df=ds.get('df'); schema={str(x) for x in df.columns} if hasattr(df,'columns') else set(); fields=[str(x) for x in p.get('source_fields',[])]; missing=[x for x in fields if x not in schema]
    if missing:return {'validation_status':'INVALID','validation_code':'INVALID_SOURCE_FIELD','invalid_fields':missing}
    sig=(str(p.get('title','')).strip().lower(),str(p.get('risk_mechanism','')).strip().lower(),tuple(sorted(fields)))
    for row in HypothesisRegistry(config.MODEL_AGENT_DIR/dataset_id).all():
        other=(str(row.get('title','')).strip().lower(),str(row.get('risk_mechanism','')).strip().lower(),tuple(sorted(str(x) for x in row.get('source_fields',[]))))
        if sig==other:return {'validation_status':'DUPLICATE','validation_code':'DUPLICATE_HYPOTHESIS','existing_hypothesis_id':row.get('hypothesis_id')}
    risky=[x for x in fields if _governance(dataset_id).get(x,{}).get('decision')=='SUSPECT_LEAKAGE']
    return {'validation_status':'LEAKAGE_RISK','validation_code':'LEAKAGE_RISK','risk_fields':risky} if risky else {'validation_status':'REVIEW','validation_code':'VALIDATED'}

def _proposal(agent_type,conversation,message,structured):
    if not structured:return []
    if agent_type=='ANALYSIS_AGENT':
        did=conversation.get('dataset_id'); rows=[]
        if not did:return rows
        for h in structured.get('hypotheses',[])[:10]:
            payload={**h,'validation':_hypothesis_validation(did,h)}; rows.append(store.add_proposal(conversation_id=conversation['conversation_id'],message_id=message['message_id'],proposal_type='HYPOTHESIS_CREATE',title=h.get('title','Hypothesis'),payload=payload,reason=h.get('risk_mechanism',''),requires_human=True))
        for f in structured.get('feature_proposals',[])[:10]:
            payload={**f,'validation':_feature_validation(did,f)}; rows.append(store.add_proposal(conversation_id=conversation['conversation_id'],message_id=message['message_id'],proposal_type='FEATURE_CANDIDATE',title=f.get('feature_name','Feature candidate'),payload=payload,reason=f.get('semantic_meaning',''),requires_human=True))
        return rows
    mapping={'SEMANTIC_ANALYSIS':'SEMANTIC_UPDATE','HYPOTHESIS':'HYPOTHESIS_CREATE','PLANNER':'EXPERIMENT_SUGGESTION','DIAGNOSIS':'DIAGNOSIS_ACTION'}; ptype=mapping.get(agent_type)
    if not ptype:return []
    rows=[store.add_proposal(conversation_id=conversation['conversation_id'],message_id=message['message_id'],proposal_type=ptype,title=structured.get('hypothesis') or structured.get('field') or structured.get('next_action') or structured.get('diagnosis_type'),payload=structured,reason=structured.get('reason') or structured.get('risk_mechanism') or structured.get('recommended_action',''),requires_human=True)]
    if agent_type=='HYPOTHESIS':
        for feature in structured.get('candidate_feature_ideas',[])[:5]:rows.append(store.add_proposal(conversation_id=conversation['conversation_id'],message_id=message['message_id'],proposal_type='FEATURE_CANDIDATE',title=feature.get('feature_name','Feature candidate'),payload=feature,reason=structured.get('risk_mechanism',''),requires_human=True))
    return rows

def _selected_metadata(binding_id,agent_type):
    try:selected=prompts.default_binding(agent_type) if binding_id in (None,'AUTO_ROUTER') else binding_id; binding=bindings.resolve(selected)[0]
    except Exception:binding=None
    try:prompt=prompts.get(agent_type)
    except Exception:prompt=None
    return binding,prompt
def _runtime_type(binding,response=None):response=response or {};return response.get('runtime_type') or response.get('execution_mode') or ('DETERMINISTIC' if not binding else 'MOCK' if binding.get('provider')=='MOCK' else 'LLM')
def _audit(conversation,message,agent_type,binding,prompt,ctx,started,success,error=None,router_reason=None,usage=None,runtime_type=None,error_type=None,error_summary=None):
    code,summary=_error(error) if error else (error_type,error_summary);usage=usage or {};meta=ctx['summary']
    return store.add_call(conversation_id=conversation['conversation_id'],message_id=message['message_id'],agent_type=agent_type,provider=binding.get('provider') if binding else None,binding_id=binding.get('binding_id') if binding else None,model=binding.get('model') if binding else None,prompt_version=prompt.get('prompt_id') if prompt else None,input_context_hash=ctx['hash'],context_summary=meta,context_id=meta.get('context_id'),context_items_count=meta.get('context_items_count'),estimated_context_tokens=meta.get('estimated_context_tokens'),sources_used=meta.get('sources_used',[]),latency_ms=round((time.perf_counter()-started)*1000),prompt_tokens=usage.get('prompt_tokens'),completion_tokens=usage.get('completion_tokens'),total_tokens=usage.get('total_tokens'),success=success,error_type=code,error_summary=summary,state_id=conversation.get('state_id'),experiment_id=conversation.get('experiment_id'),router_decision_reason=router_reason,execution_mode=runtime_type,runtime_type=runtime_type)

def send(cid,content,agent_type=None,binding_id=None,attachments=None,parent_message_id=None,context_options=None,focus_fields=None):
    conv=store.conversation(cid);agent_type=agent_type or conv['agent_type'];binding_id=binding_id or conv.get('default_binding_id');attachments=attachments or [];store.update_conversation(cid,{'agent_type':agent_type,'default_binding_id':binding_id});user=store.add_message(conversation_id=cid,role='user',content=content,attachments=attachments,agent_type=agent_type,status='SUCCESS',parent_message_id=parent_message_id);ctx=_context(conv,agent_type,attachments,content,context_options,focus_fields);assistant=store.add_message(conversation_id=cid,role='assistant',agent_type=agent_type,status='PENDING',parent_message_id=parent_message_id,context_id=ctx['summary'].get('context_id'),context_hash=ctx['hash']);started=time.perf_counter();binding,prompt=_selected_metadata(binding_id,agent_type)
    try:
        result=runtime.chat(agent_type,_history(cid),binding_id,ctx['text']);binding=result['binding'];prompt=result['prompt'];response=result['result'];usage=response.get('usage',{});rtype=_runtime_type(binding,response);proposals=_proposal(agent_type,conv,assistant,result['structured']);call=_audit(conv,assistant,agent_type,binding,prompt,ctx,started,True,router_reason=result['router_decision_reason'],usage=usage,runtime_type=rtype);assistant=store.update_message(assistant['message_id'],{'content':response['content'],'binding_id':binding['binding_id'],'provider':binding['provider'],'model':response.get('model',binding['model']),'prompt_version':prompt['prompt_id'],'tool_calls':_tools(ctx),'proposal_ids':[p['proposal_id'] for p in proposals],'latency_ms':call['latency_ms'],'prompt_tokens':usage.get('prompt_tokens'),'completion_tokens':usage.get('completion_tokens'),'total_tokens':usage.get('total_tokens'),'status':'SUCCESS','execution_mode':rtype,'runtime_type':rtype,'structured_output_status':'VALIDATED' if result['structured'] else 'NOT_APPLICABLE'});return {'user_message':user,'assistant_message':assistant,'proposals':proposals,'trace':call,'structured':result['structured'],'context':ctx['summary']}
    except Exception as exc:
        rtype=_runtime_type(binding);call=_audit(conv,assistant,agent_type,binding,prompt,ctx,started,False,error=exc,runtime_type=rtype);store.update_message(assistant['message_id'],{'binding_id':binding.get('binding_id') if binding else None,'provider':binding.get('provider') if binding else None,'model':binding.get('model') if binding else None,'prompt_version':prompt.get('prompt_id') if prompt else None,'runtime_type':rtype,'execution_mode':rtype,'structured_output_status':'INVALID','status':'FAILED','error':f"{call['error_type']}: {call['error_summary']}"});raise

def stream(cid,content,agent_type=None,binding_id=None,attachments=None,parent_message_id=None,context_options=None,focus_fields=None)->Iterator[str]:
    selected=agent_type or store.conversation(cid)['agent_type']
    if selected!='GENERAL_CHAT':
        try:
            result=send(cid,content,agent_type,binding_id,attachments,parent_message_id,context_options,focus_fields); yield _sse('start',{'user_message':result['user_message'],'assistant_message':{**result['assistant_message'],'content':''}});yield _sse('delta',{'message_id':result['assistant_message']['message_id'],'content':result['assistant_message']['content']});yield _sse('done',{'message':result['assistant_message'],'proposals':result['proposals'],'trace':result['trace'],'structured':result['structured'],'context':result['context']})
        except Exception as exc:yield _sse('error',{'message':{'status':'FAILED','error':str(exc)}})
        return
    conv=store.conversation(cid);binding_id=binding_id or conv.get('default_binding_id');attachments=attachments or [];user=store.add_message(conversation_id=cid,role='user',content=content,attachments=attachments,agent_type=selected,status='SUCCESS',parent_message_id=parent_message_id);ctx=_context(conv,selected,attachments,content,context_options,focus_fields);assistant=store.add_message(conversation_id=cid,role='assistant',agent_type=selected,status='STREAMING',context_hash=ctx['hash']);event=threading.Event();cancellations[assistant['message_id']]=event;started=time.perf_counter();chunks=[];meta=None;binding,prompt=_selected_metadata(binding_id,selected);yield _sse('start',{'user_message':user,'assistant_message':assistant})
    try:
        for chunk,meta in runtime.stream(selected,_history(cid),binding_id,ctx['text']):
            if event.is_set():rtype=_runtime_type(binding);call=_audit(conv,assistant,selected,binding,prompt,ctx,started,False,runtime_type=rtype,error_type='CANCELLED',error_summary='Cancelled by user');saved=store.update_message(assistant['message_id'],{'content':''.join(chunks),'status':'CANCELLED','runtime_type':rtype,'execution_mode':rtype});yield _sse('cancelled',{'message':saved,'trace':call});return
            binding=meta.get('binding',binding);prompt=meta.get('prompt',prompt);chunks.append(chunk);store.update_message(assistant['message_id'],{'content':''.join(chunks)});yield _sse('delta',{'message_id':assistant['message_id'],'content':chunk})
        response=meta['result'];usage=response.get('usage',{});rtype=_runtime_type(binding,response);call=_audit(conv,assistant,selected,binding,prompt,ctx,started,True,router_reason=meta['router_decision_reason'],usage=usage,runtime_type=rtype);saved=store.update_message(assistant['message_id'],{'content':''.join(chunks),'binding_id':binding['binding_id'],'provider':binding['provider'],'model':binding['model'],'prompt_version':prompt['prompt_id'],'tool_calls':_tools(ctx),'latency_ms':call['latency_ms'],'status':'SUCCESS','execution_mode':rtype,'runtime_type':rtype});yield _sse('done',{'message':saved,'proposals':[],'trace':call})
    except Exception as exc:
        rtype=_runtime_type(binding);call=_audit(conv,assistant,selected,binding,prompt,ctx,started,False,error=exc,runtime_type=rtype);saved=store.update_message(assistant['message_id'],{'content':''.join(chunks),'status':'FAILED','error':f"{call['error_type']}: {call['error_summary']}"});yield _sse('error',{'message':saved,'trace':call})
    finally:cancellations.pop(assistant['message_id'],None)

def _sse(event,data):return f"event: {event}\ndata: {json.dumps(data,ensure_ascii=False)}\n\n"
def cancel(mid):
    if mid in cancellations:cancellations[mid].set();store.update_message(mid,{'status':'CANCELLED'});return True
    return False
def decide_proposal(pid,accept):
    p=store.proposal(pid)
    if p['status']!='PENDING':raise ValueError('Proposal already decided')
    if not accept:return store.update_proposal(pid,'REJECTED_BY_USER' if 'validation' in p.get('payload',{}) else 'REJECTED')
    validation=p.get('payload',{}).get('validation',{})
    if validation.get('validation_status') in {'INVALID','DUPLICATE','LEAKAGE_RISK'}:raise ValueError(validation.get('validation_code','PROPOSAL_BLOCKED'))
    conv=store.conversation(p['conversation_id']);did=conv.get('dataset_id');payload=p['payload'];oid=None
    if did and p['proposal_type']=='HYPOTHESIS_CREATE':
        oid=f"H_LLM_{uuid.uuid4().hex[:10]}";HypothesisRegistry(config.MODEL_AGENT_DIR/did).add({'hypothesis_id':oid,'title':payload.get('title'),'evidence_type':'LLM_PROPOSAL','evidence':payload.get('evidence'),'risk_mechanism':payload.get('risk_mechanism'),'source_fields':payload.get('source_fields',[]),'candidate_features':[],'expected_direction':payload.get('expected_direction'),'expected_benefit':'Pending deterministic validation','confidence':payload.get('confidence'),'estimated_cost':payload.get('estimated_cost'),'status':'PROPOSED','related_experiments':[],'source_message_id':p['message_id']})
    elif did and p['proposal_type']=='FEATURE_CANDIDATE':
        oid=f"F_LLM_{uuid.uuid4().hex[:10]}";FeatureRegistry(config.MODEL_AGENT_DIR/did).add({'feature_id':oid,'feature_name':payload.get('feature_name'),'feature_version':'1.0','feature_type':payload.get('feature_type','RAW'),'source_fields':payload.get('source_fields',[]),'source_feature_ids':[],'semantic_domain':'LLM_PROPOSAL','semantic_meaning':payload.get('semantic_meaning'),'formula':payload.get('formula'),'calculation_description':payload.get('semantic_meaning'),'generation_reason':p['reason'],'hypothesis_id':None,'experiment_id':None,'expected_direction':payload.get('expected_direction'),'status':'PROPOSED','validation_result':validation,'lr_eligible':False,'lgbm_eligible':False,'approved':False,'source_message_id':p['message_id']})
    is_analysis='validation' in payload
    return store.update_proposal(pid,('SAVED' if oid else 'ACCEPTED') if is_analysis else ('EXECUTED' if oid else 'ACCEPTED'),oid)
def binding_views():
    calls=store.calls({});rows=[]
    for b in bindings.all():
        own=[x for x in calls if x.get('binding_id')==b['binding_id']];success=[x for x in own if x.get('success')];b['usage']={'calls':len(own),'success_rate':len(success)/len(own) if own else None,'avg_latency_ms':round(sum(x.get('latency_ms') or 0 for x in own)/len(own)) if own else None,'total_tokens':sum(x.get('total_tokens') or 0 for x in own),'last_used':own[0]['created_at'] if own else None};rows.append(b)
    return rows
