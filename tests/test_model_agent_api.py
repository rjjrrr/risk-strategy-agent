from fastapi.testclient import TestClient
import numpy as np
import pandas as pd

from backend.app import config
from backend.app.core.governance import govern
from backend.app.main import app
from backend.app.services.analysis_service import DATASETS
from backend.app.services.model_agent_service import agent


def main_data(n: int = 5000) -> pd.DataFrame:
    rng=np.random.default_rng(42); long=rng.gamma(5,10,n); ratio=np.clip(rng.beta(2,5,n)*1.5,0,1.5); short=long*ratio
    income=rng.lognormal(10,.5,n); debt=rng.gamma(3,10000,n); nonlinear=rng.normal(size=n)
    logit=-2.3+2.4*ratio+.000015*debt-.000008*income+.9*(nonlinear>1); target=rng.binomial(1,1/(1+np.exp(-logit)))
    return pd.DataFrame({'apply_time':pd.date_range('2024-01-01',periods=n,freq='h'),'is_old':0,'target7':target,'query_cnt_7d':short,'query_cnt_90d':long,'monthly_income':income,'debt_balance':debt,'nonlinear_signal':nonlinear,'drift_feature':rng.normal(np.arange(n)/n*2,1,n),'overdue_days':target*10+rng.normal(0,1,n),'customer_id':[f'C{i:07d}' for i in range(n)]})


def test_model_agent_http_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(config,'MODEL_AGENT_DIR',tmp_path/'model_agent')
    dataset_id='api_v1_test'; frame=main_data(1800); _,meta=govern(frame,'target7','is_old')
    DATASETS[dataset_id]={'df':frame,'governance':meta,'rules':[]}
    client=TestClient(app)
    try:
        response=client.post(f'/api/model-agent/{dataset_id}/run',json={'application_time_field':'apply_time'})
        assert response.status_code==200, response.text
        assert response.json()['segment']=='NEW'
        summary=client.get(f'/api/model-agent/{dataset_id}/summary')
        assert summary.status_code==200 and summary.json()['state']['current_state_id']
        features=client.get(f'/api/model-agent/{dataset_id}/features').json()
        assert features and features[0]['formula']
        proposal=client.post(f'/api/model-agent/{dataset_id}/approvals',json={'action_type':'PRODUCTION_FEATURE_APPROVAL','payload':{'feature_ids':[features[0]['feature_id']]},'reason':'regression approval test','impact':'feature becomes production-approved'})
        assert proposal.status_code==200
        approval_id=proposal.json()['approval_id']
        decision=client.post(f'/api/model-agent/{dataset_id}/approvals/{approval_id}/decision',json={'decision':'APPROVE','decided_by':'pytest'})
        assert decision.status_code==200 and decision.json()['status']=='APPROVED'
        approved=client.get(f'/api/model-agent/{dataset_id}/features').json()[0]
        assert approved['status']=='APPROVED' and approved['approved'] is True
        report=client.get(f'/api/model-agent/{dataset_id}/report')
        assert report.status_code==200 and '模型实验报告' in report.text
        state=agent(dataset_id).state_store.load()
        state['evaluation_state']['non_finite']={'nan':float('nan'),'positive_infinity':float('inf')}
        agent(dataset_id).state_store.save(state)
        persisted=agent(dataset_id).state_store.state_path.read_text(encoding='utf-8')
        assert 'NaN' not in persisted and 'Infinity' not in persisted
        state_response=client.get(f'/api/model-agent/{dataset_id}/state')
        assert state_response.status_code==200
        assert state_response.json()['evaluation_state']['non_finite']=={'nan':None,'positive_infinity':None}

        nan_dataset='api_nan_summary'
        DATASETS[nan_dataset]={'df':pd.DataFrame({'is_old':[0,0],'target7':[np.nan,np.nan]})}
        nan_summary=client.get(f'/api/datasets/{nan_dataset}/summary')
        assert nan_summary.status_code==200 and nan_summary.json()['NEW_bad_rate'] is None
        DATASETS.pop(nan_dataset,None)
    finally:
        DATASETS.pop(dataset_id,None)
