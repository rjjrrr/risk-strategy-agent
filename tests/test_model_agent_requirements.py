from pathlib import Path

import numpy as np
import pandas as pd

from core.model_agent.ablation import FeatureAblationEvaluator
from core.model_agent.approval import HumanApprovalManager
from core.model_agent.diagnosis import DiagnosisAgent
from core.model_agent.evaluation import Evaluator
from core.model_agent.experiments import ExperimentManager
from core.model_agent.features import FeatureGenerator
from core.model_agent.hypothesis import HypothesisAgent
from core.model_agent.planner import PlannerAgent
from core.model_agent.registry import ApprovalRegistry, DiagnosisRegistry, ExperimentRegistry, FeatureRegistry, HypothesisRegistry
from core.model_agent.semantic import SemanticAnalysisAgent
from core.model_agent.state import ModelAgentStateStore
from core.model_agent.validation import CheapValidator, select_feature_pools


def _frame():
    rng=np.random.default_rng(7); n=500
    long=rng.uniform(5,100,n); ratio=rng.uniform(0,1,n); short=long*ratio; y=(ratio+rng.normal(0,.25,n)>.7).astype(int)
    return pd.DataFrame({'query_cnt_7d':short,'query_cnt_90d':long,'mystery_x':rng.normal(size=n),'target7':y,'is_old':0,'apply_time':pd.date_range('2025-01-01',periods=n,freq='h'),'overdue_days':y*10})


def _governance():
    return pd.DataFrame([
        {'field':'query_cnt_7d','semantic_type':'NORMAL_FEATURE','decision':'KEEP'},
        {'field':'query_cnt_90d','semantic_type':'NORMAL_FEATURE','decision':'KEEP'},
        {'field':'mystery_x','semantic_type':'NORMAL_FEATURE','decision':'KEEP'},
        {'field':'apply_time','semantic_type':'DATETIME','decision':'KEEP'},
        {'field':'overdue_days','semantic_type':'POST_LOAN_FEATURE','decision':'SUSPECT_LEAKAGE'},
    ])


def _semantics(): return SemanticAnalysisAgent().analyze(_frame(),_governance())


def _hypothesis(tmp_path): return HypothesisAgent(HypothesisRegistry(tmp_path)).propose(_semantics(),[])[0]


def _metrics(auc=.66,ks=.25,count=4,gap=.02,lift=1.8):
    return {'oot_auc':auc,'oot_ks':ks,'lift_at_10':lift,'train_oot_auc_gap':gap,'feature_count':count}


def test_semantic_analysis_schema():
    required={'field','business_meaning','semantic_role','risk_domain','semantic_group','allowed_feature_ops','forbidden_feature_ops','confidence','reason'}
    assert required <= set(_semantics()[0])


def test_low_confidence_semantic_guard():
    row=next(x for x in _semantics() if x['field']=='mystery_x')
    assert row['confidence']=='LOW' and {'RATIO','DIFFERENCE'} <= set(row['forbidden_feature_ops'])


def test_hypothesis_registry(tmp_path):
    row=_hypothesis(tmp_path)
    stored=HypothesisRegistry(tmp_path).get(row['hypothesis_id'])
    assert stored['hypothesis_id']==row['hypothesis_id'] and stored['risk_mechanism']==row['risk_mechanism']


def test_feature_registry(tmp_path):
    feature=FeatureGenerator(FeatureRegistry(tmp_path)).generate(_frame(),_hypothesis(tmp_path))[0]
    assert FeatureRegistry(tmp_path).get(feature['feature_id'])['feature_name']==feature['feature_name']


def test_feature_formula_lineage(tmp_path):
    feature=FeatureGenerator(FeatureRegistry(tmp_path)).generate(_frame(),_hypothesis(tmp_path))[0]
    assert feature['formula']=='query_cnt_7d / max(query_cnt_90d, 1)' and feature['source_fields']==['query_cnt_7d','query_cnt_90d']


def test_feature_rebuild(tmp_path):
    df=_frame(); feature=FeatureGenerator(FeatureRegistry(tmp_path)).generate(df,_hypothesis(tmp_path))[0]
    assert np.allclose(FeatureGenerator.rebuild(df,feature),df.query_cnt_7d/df.query_cnt_90d)


def test_feature_novelty():
    df=_frame(); dev=pd.Series(np.arange(len(df))<350,index=df.index)
    result=CheapValidator().validate('ratio',df.query_cnt_7d/df.query_cnt_90d,df.target7,dev,~dev,pd.DataFrame({'duplicate':df.query_cnt_7d/df.query_cnt_90d}))
    assert result['feature_novelty']=='REDUNDANT_FEATURE'


def test_lr_feature_pool():
    row={'feature_name':'x','feature_type':'RATIO','semantic_domain':'CREDIT','validation_result':{'status':'PROMISING','psi':.01,'missing_rate':0,'max_existing_spearman':.1}}
    assert select_feature_pools([row])[0]==['x']


def test_lgbm_feature_pool():
    row={'feature_name':'x','feature_type':'RATIO','semantic_domain':'CREDIT','validation_result':{'status':'REVIEW','psi':.2,'missing_rate':0,'max_existing_spearman':.1}}
    assert select_feature_pools([row])[1]==['x']


def test_cheap_validation():
    df=_frame(); dev=pd.Series(np.arange(len(df))<350,index=df.index)
    result=CheapValidator().validate('ratio',df.query_cnt_7d/df.query_cnt_90d,df.target7,dev,~dev)
    assert {'iv','psi','lift','pearson_target','spearman_target','status'} <= set(result)


def test_experiment_registry(tmp_path):
    registry=ExperimentRegistry(tmp_path); registry.add({'experiment_id':'E1','experiment_type':'FEATURE_ADD','changes':{},'model_type':'LR'})
    assert registry.get('E1')['experiment_type']=='FEATURE_ADD'


def _store(tmp_path):
    store=ModelAgentStateStore(tmp_path,'d'); store.create()
    snap=store.snapshot(parent_state_id=None,experiment_id=None,dataset_version='D1',feature_pool_version='F1',model_config_version='M1',lr_features=['x'],lgbm_features=['x'],model_type='LR',model_params={},metrics=_metrics(),is_best=True,is_stable=True)
    return store,snap


def test_state_snapshot(tmp_path): assert len(_store(tmp_path)[0].snapshots())==1


def test_best_state(tmp_path):
    store,snap=_store(tmp_path); assert store.load()['best_state_id']==snap['state_id']


def test_last_stable_state(tmp_path):
    store,snap=_store(tmp_path); assert store.load()['last_stable_state_id']==snap['state_id']


def test_experiment_accept(): assert Evaluator().decide(_metrics(),_metrics(.67,.27,5))['decision']=='ACCEPT_PERFORMANCE'


def test_experiment_reject(): assert Evaluator().decide(_metrics(),_metrics(.55,.1,5,.2))['decision']=='REJECT'


def test_rollback(tmp_path):
    store,snap=_store(tmp_path); store.snapshot(parent_state_id=snap['state_id'],experiment_id='E2',dataset_version='D1',feature_pool_version='F2',model_config_version='M2',lr_features=['x','z'],lgbm_features=['x'],model_type='LR',model_params={},metrics=_metrics(.64),is_best=False,is_stable=False)
    assert store.rollback()['state_id']==snap['state_id']


def test_duplicate_experiment(tmp_path):
    store,_=_store(tmp_path); manager=ExperimentManager(ExperimentRegistry(tmp_path),store)
    manager.start('FEATURE_ADD','H1','add',{'added_features':['F1']},'LR')
    try: manager.start('FEATURE_ADD','H2','same',{'added_features':['F1']},'LR')
    except ValueError as exc: assert 'DUPLICATE_EXPERIMENT' in str(exc)
    else: raise AssertionError('duplicate experiment accepted')


def test_diagnosis_overfitting(tmp_path):
    rows=DiagnosisAgent(DiagnosisRegistry(tmp_path)).diagnose(_metrics(gap=.2))
    assert any(x['diagnosis_type']=='OVERFITTING' for x in rows)


def test_diagnosis_drift(tmp_path):
    rows=DiagnosisAgent(DiagnosisRegistry(tmp_path)).diagnose(_metrics(),feature_validations=[{'feature':'x','psi':.4}])
    assert any(x['diagnosis_type']=='FEATURE_DRIFT' for x in rows)


def test_leakage_isolation():
    row=next(x for x in _semantics() if x['field']=='overdue_days')
    assert row['semantic_role']=='POST_LOAN_FEATURE' and 'MODEL_INPUT_RAW' in row['forbidden_feature_ops']


def test_human_approval(tmp_path):
    store,_=_store(tmp_path); manager=HumanApprovalManager(ApprovalRegistry(tmp_path),store)
    row=manager.propose('PRODUCTION_FEATURE_APPROVAL',{'feature_ids':['F1']},'validated','production change')
    assert manager.decide(row['approval_id'],'APPROVE')['status']=='APPROVED'


def test_agent_stop_conditions():
    state={'pending_human_approval':[],'round_index':3,'max_rounds':3,'budget':{'experiments':4}}
    assert PlannerAgent.stop_reason(state,[])=='MAX_AGENT_ROUNDS_REACHED'


def test_rule_group_feature_rebuild(tmp_path):
    rules=[{'segment':'NEW','rule_group_id':'G1','rule_id':'R1','is_representative':True,'_mask_global':[1,0,1]},{'segment':'NEW','rule_group_id':'G1','rule_id':'R2','_mask_global':[0,1,1]}]
    generator=FeatureGenerator(FeatureRegistry(tmp_path)); frame,records=generator.generate_rule_group_features(rules,3)
    masks={'R1':[1,0,1],'R2':[0,1,1]}; rep=next(x for x in records if x['aggregation']=='representative')
    assert frame[rep['feature_name']].tolist()==generator.rebuild(pd.DataFrame(index=range(3)),rep,masks).tolist()


def test_ablation_requires_approval():
    full=_metrics(count=5); without={**full,'feature_count':4}
    row=FeatureAblationEvaluator().assess(full,{'x':without})[0]
    assert row['decision']=='REMOVE_CANDIDATE' and row['requires_human_approval']


def test_changelog_updated():
    text=(Path(__file__).parents[1]/'CHANGELOG_AGENT.md').read_text(encoding='utf-8')
    assert all(f'Change #{index:03d}' in text for index in range(1,10))
