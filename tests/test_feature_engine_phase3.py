import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app import config
from backend.app.main import app
from backend.app.services import agent_chat_service,analysis_service,context_service,feature_engine_service
from core.analysis_state import new_state
from core.context import ContextRequest
from core.feature_engine.ast import normalized_ast,operators,parse_expression
from core.feature_engine.capability import FeatureCapabilityRegistry
from core.feature_engine.compiler import FeatureCompiler
from core.feature_engine.executor import FeatureExecutor
from core.feature_engine.normalizer import normalize_proposal
from core.feature_engine.schemas import FeatureExecutionPlan,FeatureSpec
from core.llm.storage import ChatStore


@pytest.fixture
def engine_env(tmp_path,monkeypatch):
    did='phase3-dataset';df=pd.DataFrame({
        '__row_id__':range(8),'target7':[0,1,0,1,0,1,0,1],'is_old':[0]*8,
        'query_cnt_7d':[10,0,4,8,2,6,9,3],'query_cnt_90d':[20,0,8,16,4,12,18,6],
        'monthly_income':[2000,5000,2500,7000,3000,8000,1500,9000],
        'device_risk_level':['RED','GREEN','AMBER','RED','GREEN','RED','AMBER','GREEN'],
        'overdue_days':[0,1,0,2,0,3,0,4],
        'user_id':['u1','u1','u2','u3','u1','u2','u4','u1'],
        'device_id':['d1','d1','d1','d2','d1','d1','d2','d1'],
        'ip':['ip1','ip1','ip1','ip2','ip1','ip1','ip2','ip1'],
        'create_time':pd.to_datetime(['2026-01-01 00:00','2026-01-01 00:00','2026-01-01 12:00','2026-01-02 00:00','2026-01-02 01:00','2026-01-05 00:00','2026-01-10 00:00','2026-02-15 00:00'])
    })
    governance=pd.DataFrame([
        {'field':c,'semantic_type':'DATETIME' if c=='create_time' else 'SUSPECT_LEAKAGE' if c=='overdue_days' else 'NORMAL_FEATURE','decision':'SUSPECT_LEAKAGE' if c=='overdue_days' else 'KEEP','detected_type':'datetime' if c=='create_time' else 'numeric_continuous','reason':'test'} for c in df.columns if c!='__row_id__'
    ])
    analysis_service.DATASETS[did]={'df':df,'governance':governance,'rules':[],'target':'target7','segment_field':'is_old','state':new_state(did,'phase3.csv',len(df),len(df.columns))}
    root=tmp_path/'models';monkeypatch.setattr(config,'MODEL_AGENT_DIR',root);monkeypatch.setattr(context_service,'CONTEXT_DIR',tmp_path/'contexts');context_service.CONTEXT_DIR.mkdir();context_service._cache.clear()
    db=tmp_path/'chat.sqlite3';chat=ChatStore(db);monkeypatch.setattr(agent_chat_service,'store',chat)
    yield did,df,chat,tmp_path
    analysis_service.DATASETS.pop(did,None)


def spec(**changes):
    base={'feature_spec_id':'FS_TEST','feature_name':'query_acceleration_7d_90d','business_intent':'7d / 90d query acceleration','feature_type':'RATIO','source_fields':['query_cnt_7d','query_cnt_90d'],'desired_logic':'7-day query count divided by 90-day query count','dsl_expression':'SAFE_DIV(query_cnt_7d,query_cnt_90d)','dataset_id':'phase3-dataset'}
    return FeatureSpec.model_validate({**base,**changes})


def compile_direct(feature_spec,schema,governance=None,sources=None,registry=None):return FeatureCompiler().compile(feature_spec,schema_fields=set(schema),governance=governance or {},available_sources=set(sources or ['CURRENT_WIDE_TABLE']),feature_registry=registry or [])


def test_capability_registry():
    result=FeatureCapabilityRegistry().summary();assert {'SAFE_DIV','POWER','BOOLEAN_OR','STD_OVER_WINDOW','ENTITY_MEAN','IS_WEEKEND','RULE_GROUP_HIT'}<=set(result['operators']);assert {'1h','24h','90d'}<=set(result['windows']);assert len(result['formula_examples'])>=5


def test_feature_spec_from_proposal():
    result=normalize_proposal({'feature_name':'ratio','feature_type':'RATIO','source_fields':['a','b'],'semantic_meaning':'ratio','formula':'safe_div(a,b)'},'d')
    assert result.feature_type=='RATIO' and result.dsl_expression=='safe_div(a,b)' and result.required_data_sources==['CURRENT_WIDE_TABLE']


def test_ast_parser_and_normalization():
    node=parse_expression('safe_div(query_cnt_7d, query_cnt_90d)');assert operators(node)==['SAFE_DIV'];assert normalized_ast(node)==normalized_ast(parse_expression('SAFE_DIV(query_cnt_7d,query_cnt_90d)'))


def test_infix_arithmetic_is_compiled_to_safe_dsl():
    division=parse_expression('query_cnt_7d / query_cnt_90d')
    composite=parse_expression('(query_cnt_7d + 1) * 2 - query_cnt_90d')
    business_fields=parse_expression('AppRiskVar__app_list_num_7days_s_total_pct / AppRiskVar__app_list_num_90days_s_total_pct')
    assert operators(division)==['SAFE_DIV']
    assert operators(composite)==['ADD','MUL','SUB']
    assert operators(business_fields)==['SAFE_DIV']
    plan=compile_direct(spec(dsl_expression='query_cnt_7d / query_cnt_90d'),['query_cnt_7d','query_cnt_90d'])
    assert plan.compiler_status=='SUPPORTED_TEMPLATE' and plan.operators==['SAFE_DIV']


def test_ast_validator():
    unsupported=compile_direct(spec(dsl_expression='UNKNOWN_OP(query_cnt_7d)'),['query_cnt_7d','query_cnt_90d'])
    missing=compile_direct(spec(dsl_expression='SAFE_DIV(query_cnt_7d,missing_field)'),['query_cnt_7d','query_cnt_90d'])
    assert unsupported.compiler_status=='NEEDS_NEW_OPERATOR' and unsupported.capability_gap.missing_operator==['UNKNOWN_OP']
    assert missing.compiler_status=='INVALID_SOURCE_FIELD'


@pytest.mark.parametrize('expression',['__import__("os").system("x")','lambda x: x','df["x"]','import os','open("secret")'])
def test_malicious_expression_block(expression):
    plan=compile_direct(spec(dsl_expression=expression),['query_cnt_7d','query_cnt_90d']);assert plan.compiler_status=='INVALID_EXPRESSION'


def test_column_safe_div():
    frame=pd.DataFrame({'a':[2,1,np.nan,4],'b':[1,0,2,np.nan]});s=spec(source_fields=['a','b'],dsl_expression='SAFE_DIV(a,b)');plan=compile_direct(s,frame.columns);values=FeatureExecutor().execute(s,plan,frame)
    assert values.iloc[0]==2 and values.iloc[1:].isna().all() and plan.compiler_status=='SUPPORTED_TEMPLATE'


def test_infix_division_executes_with_zero_denominator_guard():
    frame=pd.DataFrame({'a':[2,1],'b':[1,0]});s=spec(source_fields=['a','b'],dsl_expression='a / b');plan=compile_direct(s,frame.columns);values=FeatureExecutor().execute(s,plan,frame)
    assert values.iloc[0]==2 and pd.isna(values.iloc[1])


def test_window_count_24h_and_no_future_leakage(engine_env):
    _,df,_,_=engine_env;s=spec(feature_spec_id='FS_WIN',feature_name='device_apply_cnt_24h',feature_type='TIME_WINDOW_AGG',source_fields=['device_id','create_time'],entity_key='device_id',application_time_field='create_time',time_window='24h',required_data_sources=['APPLICATION_EVENT_TABLE'],dsl_expression='COUNT_OVER_WINDOW(device_id,create_time,"24h")')
    plan=compile_direct(s,df.columns,sources=['CURRENT_WIDE_TABLE','APPLICATION_EVENT_TABLE']);values=FeatureExecutor().execute(s,plan,df)
    assert plan.compiler_status=='COMPOSABLE_DSL';assert values.iloc[0]==0 and values.iloc[1]==0  # same timestamp is excluded
    assert values.iloc[2]==2 and values.iloc[4]==1  # only the 13-hour-prior d1 event contributes; future rows do not


def test_window_no_future_leakage(engine_env):
    _,df,_,_=engine_env;s=spec(feature_spec_id='FS_FUTURE',feature_type='TIME_WINDOW_AGG',source_fields=['device_id','create_time'],entity_key='device_id',application_time_field='create_time',time_window='24h',required_data_sources=['APPLICATION_EVENT_TABLE'],dsl_expression='COUNT_OVER_WINDOW(device_id,create_time,"24h")')
    plan=compile_direct(s,df.columns,sources=['CURRENT_WIDE_TABLE','APPLICATION_EVENT_TABLE']);values=FeatureExecutor().execute(s,plan,df)
    assert values.iloc[0]==0 and values.iloc[1]==0 and values.iloc[2]==2


def test_entity_nunique_30d(engine_env):
    _,df,_,_=engine_env;s=spec(feature_spec_id='FS_ENTITY',feature_name='ip_shared_user_cnt_30d',feature_type='TIME_WINDOW_AGG',source_fields=['ip','user_id','create_time'],entity_key='ip',application_time_field='create_time',time_window='30d',required_data_sources=['IP_RELATION_TABLE'],dsl_expression='ENTITY_WINDOW_NUNIQUE(ip,user_id,create_time,"30d")')
    plan=compile_direct(s,df.columns,sources=['CURRENT_WIDE_TABLE','IP_RELATION_TABLE']);values=FeatureExecutor().execute(s,plan,df)
    assert plan.compiler_status=='COMPOSABLE_DSL';assert values.iloc[0]==0 and values.iloc[1]==0 and values.iloc[2]==1 and values.iloc[5]==2 and values.iloc[7]==0


def test_conditional_count_window(engine_env):
    _,df,_,_=engine_env;s=spec(feature_spec_id='FS_COND',feature_name='risky_device_cnt_7d',feature_type='CONDITIONAL_AGG',source_fields=['device_id','create_time','query_cnt_7d'],entity_key='device_id',time_window='7d',required_data_sources=['APPLICATION_EVENT_TABLE'],dsl_expression='CONDITIONAL_COUNT(device_id,create_time,GT(query_cnt_7d,5),"7d")')
    plan=compile_direct(s,df.columns,sources=['CURRENT_WIDE_TABLE','APPLICATION_EVENT_TABLE']);values=FeatureExecutor().execute(s,plan,df)
    assert plan.compiler_status=='COMPOSABLE_DSL' and values.iloc[0]==0 and values.iloc[2]==1 and values.iloc[5]==1


def test_rule_group_derived(engine_env):
    _,df,_,_=engine_env;s=spec(feature_spec_id='FS_RULE',feature_name='rule_group_g1_hit',feature_type='RULE_GROUP_DERIVED',source_fields=[],required_data_sources=['RULE_GROUP_ARTIFACT'],dsl_expression='RULE_GROUP_HIT("G1")');plan=compile_direct(s,df.columns,sources=['CURRENT_WIDE_TABLE','RULE_GROUP_ARTIFACT']);rules=[{'rule_group_id':'G1','_mask_global':np.array([1,0,1,0,0,0,0,0],bool)},{'rule_group_id':'G1','_mask_global':np.array([0,1,1,0,0,0,0,0],bool)}];values=FeatureExecutor().execute(s,plan,df,rules=rules)
    assert values.tolist()[:4]==[1,1,1,0]


def test_insufficient_entity_data():
    s=spec(feature_type='TIME_WINDOW_AGG',source_fields=['missing_device','create_time'],entity_key='missing_device',time_window='24h',required_data_sources=['APPLICATION_EVENT_TABLE'],dsl_expression='COUNT_OVER_WINDOW(missing_device,create_time,"24h")')
    plan=compile_direct(s,['create_time'],sources=['CURRENT_WIDE_TABLE']);assert plan.compiler_status=='INSUFFICIENT_DATA' and plan.capability_gap.missing_data_source==['APPLICATION_EVENT_TABLE']


def test_boolean_or_is_supported():
    plan=compile_direct(spec(dsl_expression='EQ(query_cnt_7d,1) or not EQ(query_cnt_90d,2)'),['query_cnt_7d','query_cnt_90d'])
    assert plan.compiler_status=='COMPOSABLE_DSL' and {'BOOLEAN_OR','NOT'}<=set(plan.operators)


def test_complex_nonlinear_and_missing_formula():
    frame=pd.DataFrame({'a':[4,-9,np.nan],'b':[2,0,3]})
    expression='ROUND(SQRT(POWER(ABS(COALESCE(a,0)),2)),1) + MOD(b,2)'
    s=spec(source_fields=['a','b'],dsl_expression=expression);plan=compile_direct(s,frame.columns);values=FeatureExecutor().execute(s,plan,frame)
    assert plan.compiler_status=='COMPOSABLE_DSL' and values.tolist()==[4.0,9.0,1.0]


def test_safe_datetime_derivations(engine_env):
    _,df,_,_=engine_env;s=spec(feature_spec_id='FS_DATE',feature_type='COLUMN_TRANSFORM',source_fields=['create_time'],dsl_expression='IF(IS_WEEKEND(create_time),HOUR(create_time),DAY_OF_WEEK(create_time))')
    governance={'create_time':{'decision':'KEEP','semantic_type':'DATETIME'}};plan=compile_direct(s,df.columns,governance);values=FeatureExecutor().execute(s,plan,df)
    assert plan.compiler_status=='COMPOSABLE_DSL' and values.notna().all()


def test_window_statistics_and_entity_aggregation(engine_env):
    _,df,_,_=engine_env
    window=spec(feature_spec_id='FS_STD_WIN',feature_type='TIME_WINDOW_AGG',source_fields=['device_id','monthly_income','create_time'],entity_key='device_id',application_time_field='create_time',time_window='24h',required_data_sources=['APPLICATION_EVENT_TABLE'],dsl_expression='STD_OVER_WINDOW(device_id,monthly_income,create_time,"24h")')
    plan=compile_direct(window,df.columns,sources=['CURRENT_WIDE_TABLE','APPLICATION_EVENT_TABLE']);values=FeatureExecutor().execute(window,plan,df)
    assert plan.compiler_status=='COMPOSABLE_DSL' and values.iloc[2]==1500
    entity=spec(feature_spec_id='FS_ENTITY_MEAN',feature_type='ENTITY_AGG',source_fields=['device_id','monthly_income'],entity_key='device_id',dsl_expression='ENTITY_MEAN(device_id,monthly_income)')
    entity_plan=compile_direct(entity,df.columns);entity_values=FeatureExecutor().execute(entity,entity_plan,df)
    assert entity_plan.compiler_status=='COMPOSABLE_DSL' and entity_values.iloc[0]==entity_values.iloc[1]


def test_leakage_block():
    leak=spec(feature_type='COLUMN_TRANSFORM',source_fields=['overdue_days'],dsl_expression='overdue_days');date=spec(feature_type='COLUMN_TRANSFORM',source_fields=['create_time'],dsl_expression='create_time')
    governance={'overdue_days':{'decision':'SUSPECT_LEAKAGE','semantic_type':'SUSPECT_LEAKAGE'},'create_time':{'decision':'KEEP','semantic_type':'DATETIME'}}
    assert compile_direct(leak,['overdue_days'],governance).compiler_status=='LEAKAGE_RISK';assert compile_direct(date,['create_time'],governance).compiler_status=='DATETIME_RAW_FORBIDDEN'


def test_datetime_raw_block():
    date=spec(feature_type='COLUMN_TRANSFORM',source_fields=['create_time'],dsl_expression='create_time')
    assert compile_direct(date,['create_time'],{'create_time':{'decision':'KEEP','semantic_type':'DATETIME'}}).compiler_status=='DATETIME_RAW_FORBIDDEN'


def test_device_score_and_combo_compile():
    device=normalize_proposal({'feature_name':'device_risk_weighted_score','feature_type':'DERIVED_NUMERIC','source_fields':['device_risk_level'],'formula':"CASE device_risk_level WHEN 'RED' THEN 3 WHEN 'AMBER' THEN 2 WHEN 'GREEN' THEN 1 ELSE 0 END",'semantic_meaning':'weighted device risk'},'d')
    combo=normalize_proposal({'feature_name':'low_income_device_risk_combo','feature_type':'DERIVED_BINARY','source_fields':['monthly_income','device_risk_level'],'formula':"IF(monthly_income <= 3187.36 AND device_risk_level == 'RED',1,0)",'semantic_meaning':'low income and red device'},'d')
    p1=compile_direct(device,['device_risk_level']);p2=compile_direct(combo,['monthly_income','device_risk_level'])
    assert p1.compiler_status=='COMPOSABLE_DSL' and {'IF','EQ'}<=set(p1.operators);assert p2.compiler_status=='COMPOSABLE_DSL' and {'IF','BOOLEAN_AND','LE','EQ'}<=set(p2.operators)


def test_feature_registry_lineage(engine_env):
    did,df,_,_=engine_env;created=feature_engine_service.create_spec(did,spec().model_dump());plan=feature_engine_service.compile_spec(did,created['feature_spec_id']);result=feature_engine_service.execute_plan(did,plan['plan_id'],user_confirmed=True);feature=result['feature']
    assert feature['status']=='GENERATED' and feature['feature_spec_id']==created['feature_spec_id'] and feature['normalized_ast'] and Path(feature['artifact_path']).exists()
    rebuilt=feature_engine_service.rebuild_feature(did,feature['feature_id']);assert rebuilt['success'] and rebuilt['statistics']['values_match'] and rebuilt['statistics']['dataset_version_match']
    duplicate=feature_engine_service.compile_spec(did,created['feature_spec_id']);assert duplicate['compiler_status']=='DUPLICATE_FEATURE' and duplicate['existing_feature_id']==feature['feature_id']
    changed=feature_engine_service.create_spec(did,spec(feature_spec_id='FS_V2',dsl_expression='SAFE_DIV(query_cnt_7d,ADD(query_cnt_90d,1))').model_dump());changed_plan=feature_engine_service.compile_spec(did,changed['feature_spec_id']);second=feature_engine_service.execute_plan(did,changed_plan['plan_id'],user_confirmed=True)['feature'];assert second['version']=='2.0' and second['feature_id']!=feature['feature_id']


def test_feature_rebuild(engine_env):
    did,_,_,_=engine_env;created=feature_engine_service.create_spec(did,spec().model_dump());plan=feature_engine_service.compile_spec(did,created['feature_spec_id']);feature=feature_engine_service.execute_plan(did,plan['plan_id'],user_confirmed=True)['feature'];rebuilt=feature_engine_service.rebuild_feature(did,feature['feature_id'])
    assert rebuilt['status']=='SUCCESS' and rebuilt['statistics']['values_match']


def test_feature_versioning(engine_env):
    did,_,_,_=engine_env;first=feature_engine_service.create_spec(did,spec().model_dump());p1=feature_engine_service.compile_spec(did,first['feature_spec_id']);f1=feature_engine_service.execute_plan(did,p1['plan_id'],user_confirmed=True)['feature'];second=feature_engine_service.create_spec(did,spec(feature_spec_id='FS_VERSION_2',dsl_expression='SAFE_DIV(query_cnt_7d,ADD(query_cnt_90d,1))').model_dump());p2=feature_engine_service.compile_spec(did,second['feature_spec_id']);f2=feature_engine_service.execute_plan(did,p2['plan_id'],user_confirmed=True)['feature']
    assert f1['version']=='1.0' and f2['version']=='2.0' and f1['feature_id']!=f2['feature_id']


def test_duplicate_ast_feature(engine_env):
    did,_,_,_=engine_env;created=feature_engine_service.create_spec(did,spec().model_dump());plan=feature_engine_service.compile_spec(did,created['feature_spec_id']);feature=feature_engine_service.execute_plan(did,plan['plan_id'],user_confirmed=True)['feature'];duplicate=feature_engine_service.compile_spec(did,created['feature_spec_id'])
    assert duplicate['compiler_status']=='DUPLICATE_FEATURE' and duplicate['existing_feature_id']==feature['feature_id']


def test_execute_requires_explicit_user_action(engine_env):
    did,_,_,_=engine_env;created=feature_engine_service.create_spec(did,spec().model_dump());plan=feature_engine_service.compile_spec(did,created['feature_spec_id'])
    with pytest.raises(ValueError,match='Explicit user confirmation'):feature_engine_service.execute_plan(did,plan['plan_id'])


def test_context_cache_invalid_after_feature(engine_env):
    did,_,chat,_=engine_env;conv=chat.create_conversation(dataset_id=did,agent_type='ANALYSIS_AGENT');request=ContextRequest(conversation_id=conv['conversation_id'],dataset_id=did)
    before=context_service.build(request,chat);created=feature_engine_service.create_spec(did,spec().model_dump());plan=feature_engine_service.compile_spec(did,created['feature_spec_id']);feature_engine_service.execute_plan(did,plan['plan_id'],user_confirmed=True);after=context_service.build(request,chat)
    assert before.context_hash!=after.context_hash and 'FEATURE_REGISTRY' in after.sources_used


def test_feature_engine_api(engine_env):
    did,_,_,_=engine_env;client=TestClient(app);assert client.get('/api/feature-engine/capabilities').status_code==200
    created=feature_engine_service.create_spec(did,spec().model_dump());compiled=client.post('/api/feature-engine/compile',json={'dataset_id':did,'feature_spec_id':created['feature_spec_id']});assert compiled.status_code==200
    blocked=client.post(f"/api/feature-engine/execute/{compiled.json()['plan_id']}",json={'dataset_id':did,'user_confirmed':False});assert blocked.status_code==400
    generated=client.post(f"/api/feature-engine/execute/{compiled.json()['plan_id']}",json={'dataset_id':did,'user_confirmed':True});assert generated.status_code==200 and generated.json()['status']=='SUCCESS'


def test_frontend_feature_engine_contract():
    page=Path('frontend/src/pages/FeatureEnginePage.tsx').read_text(encoding='utf-8');chat=Path('frontend/src/pages/AgentChatPage.tsx').read_text(encoding='utf-8')
    assert all(token in page for token in ('Proposal / Spec','Compiled','Generated','Compile','Generate Feature','Rebuild','window.confirm'))
    assert 'compileFeature' in chat and 'Generate Feature' not in chat


def test_no_eval():
    source='\n'.join(path.read_text(encoding='utf-8') for path in (Path('core/feature_engine')).glob('*.py'))
    assert not re.search(r'\beval\s*\(',source) and not re.search(r'\bexec\s*\(',source)
    assert not re.search(r'^\s*(?:from|import)\s+subprocess\b',source,re.M)
