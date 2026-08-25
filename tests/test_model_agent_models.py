import numpy as np
import pandas as pd

from core.model_agent.diagnosis import DiagnosisAgent
from core.model_agent.evaluation import Evaluator
from core.model_agent.experiments import ExperimentManager
from core.model_agent.models import ModelTrainer
from core.model_agent.registry import DiagnosisRegistry, ExperimentRegistry
from core.model_agent.state import ModelAgentStateStore


def _data(n=1200):
    rng=np.random.default_rng(12); x=rng.normal(size=n); y=(x+rng.normal(scale=.7,size=n)>1).astype(int); frame=pd.DataFrame({'x':x,'cat':np.where(x>0,'A','B')}); return frame.iloc[:800],pd.Series(y[:800]),frame.iloc[800:],pd.Series(y[800:])


def test_lr_and_lgbm_baseline(tmp_path):
    xd,yd,xo,yo=_data(); trainer=ModelTrainer(tmp_path)
    lr=trainer.train('LR',xd,yd,xo,yo,'lr_base'); lgbm=trainer.train('LGBM',xd,yd,xo,yo,'lgbm_base')
    assert lr['metrics']['oot_auc']>.75 and lgbm['metrics']['oot_auc']>.75
    for result in (lr,lgbm):
        metrics=result['metrics']
        assert metrics['overall_rows']==metrics['dev_rows']+metrics['oot_rows']
        assert 0 <= metrics['overall_auc'] <= 1
        assert metrics['selection_metric']=='oot_auc'
        assert metrics['metrics_version']=='2.0'
    assert (tmp_path/'lr_base.pkl').exists() and (tmp_path/'lgbm_base.txt').exists()


def test_evaluator_accept_reject_and_diagnosis(tmp_path):
    evaluator=Evaluator({'min_oot_auc':.6,'min_oot_ks':.1})
    baseline={'oot_auc':.65,'oot_ks':.25,'lift_at_10':2.,'train_oot_auc_gap':.02,'feature_count':10}
    better={**baseline,'oot_auc':.66}; rejected={**baseline,'oot_auc':.55}
    assert evaluator.decide(baseline,better)['decision']=='ACCEPT_PERFORMANCE'
    assert evaluator.decide(baseline,rejected)['decision']=='REJECT'
    findings=DiagnosisAgent(DiagnosisRegistry(tmp_path)).diagnose({**baseline,'train_oot_auc_gap':.2},feature_validations=[{'feature':'x','psi':.3}])
    assert {x['diagnosis_type'] for x in findings}=={'OVERFITTING','FEATURE_DRIFT'}


def test_experiment_reject_rolls_back_and_duplicate(tmp_path):
    store=ModelAgentStateStore(tmp_path,'d');store.create(); stable=store.snapshot(parent_state_id=None,experiment_id=None,dataset_version='D1',feature_pool_version='F1',model_config_version='M1',lr_features=['x'],lgbm_features=['x'],model_type='LR',model_params={},metrics={'oot_auc':.65},is_best=True,is_stable=True)
    manager=ExperimentManager(ExperimentRegistry(tmp_path),store,Evaluator({'min_oot_auc':.6,'min_oot_ks':.1}))
    exp=manager.start('FEATURE_ADD','H1','add y',{'added_features':['y']},'LR')
    metrics={'oot_auc':.55,'oot_ks':.1,'lift_at_10':1.,'train_oot_auc_gap':.2,'feature_count':2}
    result=manager.finish(exp['experiment_id'],{'oot_auc':.65,'oot_ks':.2,'lift_at_10':1.5,'train_oot_auc_gap':.02,'feature_count':1},metrics,snapshot_args={'dataset_version':'D1','feature_pool_version':'F2','model_config_version':'M1','lr_features':['x','y'],'lgbm_features':['x','y'],'model_type':'LR','model_params':{}})
    assert result['decision']=='REJECT' and store.load()['current_state_id']==stable['state_id']
    try: manager.start('FEATURE_ADD','H1','again',{'added_features':['y']},'LR')
    except ValueError as error: assert 'DUPLICATE_EXPERIMENT' in str(error)
    else: raise AssertionError('duplicate experiment was not blocked')
