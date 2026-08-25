from core.model_agent.registry import ExperimentRegistry, FeatureRegistry, HypothesisRegistry
from core.model_agent.state import ModelAgentStateStore


def test_state_snapshot_best_and_last_stable(tmp_path):
    store=ModelAgentStateStore(tmp_path,'dataset-x'); state=store.create()
    assert state['segment']=='NEW' and state['max_rounds']==3
    first=store.snapshot(parent_state_id=None,experiment_id=None,dataset_version='D1',feature_pool_version='F1',model_config_version='M1',lr_features=['x'],lgbm_features=['x'],model_type='LR',model_params={},metrics={'oot_auc':.65},is_best=True,is_stable=True)
    second=store.snapshot(parent_state_id=first['state_id'],experiment_id='E1',dataset_version='D1',feature_pool_version='F2',model_config_version='M1',lr_features=['x','y'],lgbm_features=['x','y'],model_type='LR',model_params={},metrics={'oot_auc':.60})
    state=store.load()
    assert state['current_state_id']==second['state_id']
    assert state['best_state_id']==first['state_id']==state['last_stable_state_id']
    rolled=store.rollback()
    restored=store.load()
    assert rolled['state_id']==first['state_id'] and restored['current_state_id']==first['state_id']
    assert restored['model_state']['champion']=='LR' and restored['model_state']['lr_baseline']['metrics']['oot_auc']==.65


def test_registries_and_duplicate_experiment(tmp_path):
    hypotheses=HypothesisRegistry(tmp_path); features=FeatureRegistry(tmp_path); experiments=ExperimentRegistry(tmp_path)
    hypotheses.add({'hypothesis_id':'H001','status':'PROPOSED'})
    features.add({'feature_id':'F001','formula':'a / max(b, 1)','source_fields':['a','b']})
    assert features.by_formula('a / max(b, 1)',['b','a'])['feature_id']=='F001'
    experiments.add({'experiment_id':'E001','experiment_type':'FEATURE_ADD','model_type':'LR','changes':{'added':['F001']},'decision':'REJECT'})
    assert experiments.duplicate('FEATURE_ADD',{'added':['F001']},'LR')['experiment_id']=='E001'
