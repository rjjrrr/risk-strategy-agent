import numpy as np
import pandas as pd

from core.model_agent.features import FeatureGenerator
from core.model_agent.hypothesis import HypothesisAgent
from core.model_agent.registry import FeatureRegistry, HypothesisRegistry
from core.model_agent.semantic import SemanticAnalysisAgent
from core.model_agent.validation import CheapValidator, select_feature_pools


def _governance():
    return pd.DataFrame([
        {'field':'query_cnt_7d','semantic_type':'NORMAL_FEATURE','decision':'KEEP'},
        {'field':'query_cnt_90d','semantic_type':'NORMAL_FEATURE','decision':'KEEP'},
        {'field':'mystery_x','semantic_type':'NORMAL_FEATURE','decision':'KEEP'},
    ])


def test_semantic_analysis_schema_and_low_confidence_guard():
    df=pd.DataFrame({'query_cnt_7d':[1,2,9],'query_cnt_90d':[10,10,10],'mystery_x':[1,2,3]})
    rows=SemanticAnalysisAgent().analyze(df,_governance())
    required={'field','business_meaning','semantic_role','risk_domain','possible_relations','allowed_feature_ops','forbidden_feature_ops','confidence','reason','semantic_group'}
    assert required <= set(rows[0])
    mystery=next(x for x in rows if x['field']=='mystery_x')
    assert mystery['confidence']=='LOW' and 'RATIO' in mystery['forbidden_feature_ops']


def test_hypothesis_feature_registry_formula_and_rebuild(tmp_path):
    df=pd.DataFrame({'query_cnt_7d':[1.,5.,9.],'query_cnt_90d':[10.,0.,3.]})
    semantics=SemanticAnalysisAgent().analyze(df,_governance().iloc[:2])
    hypotheses=HypothesisAgent(HypothesisRegistry(tmp_path)).propose(semantics,[])
    assert hypotheses and hypotheses[0]['evidence_type']=='TIME_WINDOW_PATTERN'
    generator=FeatureGenerator(FeatureRegistry(tmp_path)); feature=generator.generate(df,hypotheses[0])[0]
    assert feature['source_fields']==['query_cnt_7d','query_cnt_90d']
    assert feature['formula']=='query_cnt_7d / max(query_cnt_90d, 1)'
    rebuilt=generator.rebuild(df,feature)
    assert np.allclose(rebuilt,[.1,5.,3.])


def test_feature_novelty_validation_and_pools():
    n=1000; rng=np.random.default_rng(4); target=pd.Series((rng.random(n)<.2).astype(int)); feature=pd.Series(target+rng.normal(0,.2,n)); dev=pd.Series([True]*700+[False]*300); oot=~dev
    result=CheapValidator().validate('signal',feature,target,dev,oot,pd.DataFrame({'duplicate':feature}))
    assert result['feature_novelty']=='REDUNDANT_FEATURE' and result['status']=='REJECTED'
    record={'feature_name':'signal','semantic_domain':'CREDIT','feature_type':'RAW','validation_result':{**result,'max_existing_spearman':0,'status':'PROMISING'}}
    lr,lgbm=select_feature_pools([record]); assert lr==['signal'] and lgbm==['signal']
