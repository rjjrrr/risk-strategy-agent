from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT=Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0,str(PROJECT_ROOT))

import numpy as np
import pandas as pd

from backend.app.core.governance import govern
from core.model_agent.ablation import FeatureAblationEvaluator
from core.model_agent.diagnosis import DiagnosisAgent
from core.model_agent.evaluation import Evaluator
from core.model_agent.experiments import ExperimentManager
from core.model_agent.models import ModelTrainer
from core.model_agent.orchestrator import ModelAgentOrchestrator
from core.model_agent.registry import DiagnosisRegistry, ExperimentRegistry
from core.model_agent.state import ModelAgentStateStore
from core.model_agent.validation import CheapValidator


def main_data(n: int = 5000) -> pd.DataFrame:
    rng=np.random.default_rng(42); t=np.arange(n)
    long=rng.gamma(5,10,n); ratio=np.clip(rng.beta(2,5,n)*1.5,0,1.5); short=long*ratio
    income=rng.lognormal(10,.5,n); debt=rng.gamma(3,10000,n); nonlinear=rng.normal(size=n)
    logit=-2.3+2.4*ratio+.000015*debt-.000008*income+.9*(nonlinear>1)
    probability=1/(1+np.exp(-logit)); target=rng.binomial(1,probability)
    return pd.DataFrame({
        'apply_time':pd.date_range('2024-01-01',periods=n,freq='h'), 'is_old':0, 'target7':target,
        'query_cnt_7d':short, 'query_cnt_90d':long, 'monthly_income':income,
        'debt_balance':debt, 'nonlinear_signal':nonlinear,
        'drift_feature':rng.normal(t/n*2,1,n), 'overdue_days':target*10+rng.normal(0,1,n),
        'customer_id':[f'C{i:07d}' for i in range(n)],
    })


def nonlinear_data(n: int = 3000) -> pd.DataFrame:
    rng=np.random.default_rng(88); x1=rng.normal(size=n); x2=rng.normal(size=n)
    target=((x1>0)^(x2>0)).astype(int)
    return pd.DataFrame({'apply_time':pd.date_range('2024-01-01',periods=n,freq='h'),'x1':x1,'x2':x2,'target7':target})


def run(output: Path) -> dict:
    output.mkdir(parents=True,exist_ok=False)
    raw=output/'raw_data'; raw.mkdir(); results_dir=output/'results'; results_dir.mkdir()
    df=main_data(); df.to_csv(raw/'model_agent_main_5000.csv',index=False)
    _,governance=govern(df,'target7','is_old')
    orchestrator=ModelAgentOrchestrator(results_dir/'agent','v1_regression')
    initial=orchestrator.run_initial(df,governance,[],'apply_time')
    experiment=orchestrator.run_next_experiment(df)

    nonlinear=nonlinear_data(); nonlinear.to_csv(raw/'nonlinear_lgbm_3000.csv',index=False)
    dev=nonlinear.iloc[:2100]; oot=nonlinear.iloc[2100:]; trainer=ModelTrainer(results_dir/'scenario_b_models')
    lr=trainer.train('LR',dev[['x1','x2']],dev.target7,oot[['x1','x2']],oot.target7,'nonlinear_lr')
    lgbm=trainer.train('LGBM',dev[['x1','x2']],dev.target7,oot[['x1','x2']],oot.target7,'nonlinear_lgbm')

    rng=np.random.default_rng(9); n=2400; x=rng.normal(size=n); y=(x+rng.normal(0,.8,n)>.8).astype(int)
    spurious=np.r_[y[:1680]+rng.normal(0,.02,1680),rng.normal(size=720)]
    overfit=pd.DataFrame({'x':x,'dev_only_proxy':spurious,'target7':y}); overfit.to_csv(raw/'overfit_2400.csv',index=False)
    overfit_model=ModelTrainer(results_dir/'scenario_c_models').train('LGBM',overfit.iloc[:1680][['x','dev_only_proxy']],overfit.target7.iloc[:1680],overfit.iloc[1680:][['x','dev_only_proxy']],overfit.target7.iloc[1680:],'overfit_lgbm')
    overfit_diagnosis=DiagnosisAgent(DiagnosisRegistry(results_dir/'scenario_c_diagnosis')).diagnose(overfit_model['metrics'])

    target=pd.Series(rng.binomial(1,.2,2000)); shifted=pd.Series(np.r_[rng.normal(0,1,1400),rng.normal(3,1,600)])
    dev_mask=pd.Series(np.arange(2000)<1400); drift=CheapValidator().validate('shifted_feature',shifted,target,dev_mask,~dev_mask)
    leakage=governance.loc[governance.field=='overdue_days',['field','decision','semantic_type']].iloc[0].to_dict()

    full={'oot_auc':.68,'oot_ks':.28,'lift_at_10':1.9,'train_oot_auc_gap':.02,'feature_count':6}
    without={**full,'oot_auc':.64,'oot_ks':.22,'lift_at_10':1.5,'feature_count':5}
    ablation=FeatureAblationEvaluator().assess(full,{'query_cnt_ratio':without})[0]

    rollback_root=results_dir/'scenario_h_rollback'; store=ModelAgentStateStore(rollback_root,'rollback'); store.create()
    stable=store.snapshot(parent_state_id=None,experiment_id=None,dataset_version='D1',feature_pool_version='F1',model_config_version='M1',lr_features=['x'],lgbm_features=['x'],model_type='LR',model_params={},metrics=full,is_best=True,is_stable=True)
    manager=ExperimentManager(ExperimentRegistry(rollback_root),store,Evaluator())
    failed=manager.start('FEATURE_ADD','H_FAIL','bad feature',{'added_features':['F_BAD']},'LR')
    failed_result=manager.finish(failed['experiment_id'],full,{'oot_auc':.55,'oot_ks':.1,'lift_at_10':1.,'train_oot_auc_gap':.2,'feature_count':7},snapshot_args={'dataset_version':'D1','feature_pool_version':'F_BAD','model_config_version':'M1','lr_features':['x','bad'],'lgbm_features':['x'],'model_type':'LR','model_params':{}})

    cases={
        'A_stable_lr':{'passed':Evaluator().hard_gate(initial['lr_baseline'])[0],'metrics':initial['lr_baseline']},
        'B_nonlinear_lgbm_better':{'passed':lgbm['metrics']['oot_auc']>lr['metrics']['oot_auc']+.15,'lr':lr['metrics'],'lgbm':lgbm['metrics']},
        'C_overfit_train_oot':{'passed':any(x['diagnosis_type']=='OVERFITTING' for x in overfit_diagnosis),'metrics':overfit_model['metrics'],'diagnosis':overfit_diagnosis},
        'D_feature_drift':{'passed':drift['psi']>=.25 and drift['status']=='REJECTED','validation':drift},
        'E_leakage_isolated':{'passed':leakage['decision']=='SUSPECT_LEAKAGE','governance':leakage},
        'F_ratio_oot_gain':{'passed':experiment.get('metrics_after',{}).get('oot_auc',0)>experiment.get('metrics_before',{}).get('oot_auc',1),'experiment':experiment,'note':'OOT gain is verified independently from the Pareto accept/reject decision.'},
        'G_ablation_rejected':{'passed':ablation['decision']=='KEEP','ablation':ablation},
        'H_failed_experiment_rollback':{'passed':failed_result['decision']=='REJECT' and store.load()['current_state_id']==stable['state_id'],'experiment':failed_result,'current_state_id':store.load()['current_state_id']},
    }
    cleaned=json.loads(json.dumps(cases,default=lambda x:x.item() if hasattr(x,'item') else str(x)))
    (results_dir/'scenario_results.json').write_text(json.dumps(cleaned,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Model Agent V1.0 大规模回归报告','',f'- 生成时间：{datetime.now().isoformat(timespec="seconds")}',f'- 主数据：5,000 行',f'- 非线性数据：3,000 行',f'- 过拟合数据：2,400 行','', '## 场景结果','']
    for name,value in cleaned.items(): lines.append(f"- {'PASS' if value['passed'] else 'FAIL'} `{name}`")
    lines += ['', '## 关键结果','',f"- LR baseline OOT AUC：{initial['lr_baseline']['oot_auc']:.4f}",f"- LightGBM nonlinear OOT AUC：{lgbm['metrics']['oot_auc']:.4f}（LR {lr['metrics']['oot_auc']:.4f}）",f"- Ratio experiment：{experiment.get('decision')}",f"- Drift PSI：{drift['psi']:.4f}",f"- Failed experiment rollback：{failed_result.get('rollback_state_id')}",'', '原始数据、模型文件、Registry、State Snapshot 与 JSON 结果均保存在本目录。']
    (output/'test_report.md').write_text('\n'.join(lines),encoding='utf-8')
    return {'output':str(output),'passed':sum(v['passed'] for v in cleaned.values()),'total':len(cleaned),'cases':cleaned}


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',default=str(PROJECT_ROOT/'test_artifacts/model_agent_v1'))
    args=parser.parse_args(); destination=Path(args.output)
    if destination.exists(): destination=destination.with_name(f"{destination.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    print(json.dumps(run(destination),ensure_ascii=False,indent=2))
