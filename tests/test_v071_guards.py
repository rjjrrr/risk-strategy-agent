import numpy as np
import pandas as pd
from core.numeric_scanner import scan_numeric
from core.category_scanner import scan_categories
from core.analysis_state import new_state, stale_downstream, SUCCESS, STALE
from core.rule_deduplicator import deduplicate
from core.reporter import write_outputs

def test_datetime_is_never_scanned_even_when_keep():
    df=pd.DataFrame({'__target__':[0,1,0,1]*4,'event_time':pd.date_range('2024-01-01',periods=16),'__segment__':['NEW']*16})
    meta=pd.DataFrame([{'field':'event_time','decision':'KEEP','detected_type':'numeric_continuous','semantic_type':'DATETIME'}])
    assert scan_numeric(df,meta,'NEW') == []
    meta.loc[0,'detected_type']='categorical_string'
    assert scan_categories(df,meta,'NEW') == []

def test_high_cardinality_numeric_has_no_equality_rule():
    df=pd.DataFrame({'__target__':[0,1]*10,'value':np.arange(20,dtype=float),'__segment__':['NEW']*20})
    meta=pd.DataFrame([{'field':'value','decision':'KEEP','detected_type':'numeric_continuous','semantic_type':'NORMAL_FEATURE'}])
    rules=scan_numeric(df,meta,'NEW')
    assert all('==' not in r['rule'] for r in rules)

def test_stale_only_marks_downstream_stages():
    state=new_state('x')
    for stage in state['stage_status']:
        state['stage_status'][stage]=SUCCESS
    stale_downstream(state,'rule_groups')
    assert state['stage_status']['candidate_rules']==SUCCESS
    assert state['stage_status']['rule_groups']==SUCCESS
    assert state['stage_status']['grading']==STALE
    assert state['stage_status']['report']==STALE

def test_jaccard_identity_and_rule_groups_use_hit_sets():
    rules=[
        {'segment':'NEW','rule_id':'NEW_R000001','grade':'B','lift':1.2,'hit_count':3,'coverage':.5,'_mask':np.array([1,1,1,0,0],bool)},
        {'segment':'NEW','rule_id':'NEW_R000002','grade':'B','lift':1.1,'hit_count':3,'coverage':.5,'_mask':np.array([1,1,1,0,0],bool)},
        {'segment':'NEW','rule_id':'NEW_R000003','grade':'C','lift':1.0,'hit_count':2,'coverage':.4,'_mask':np.array([0,0,0,1,1],bool)},
    ]
    out=deduplicate(rules,same_threshold=.9)
    assert out[0]['rule_group_id']==out[1]['rule_group_id']
    assert out[0]['rule_group_id']!=out[2]['rule_group_id']
    matrix=np.eye(3); matrix[0,1]=matrix[1,0]=1.0
    assert matrix.shape==(3,3) and np.all(np.diag(matrix)==1)

def test_report_is_utf8_and_exports_rule_id(tmp_path):
    df=pd.DataFrame({'__target__':[1,0],'__segment__':['NEW','OLD']})
    rule={'rule_id':'NEW_R000001','segment':'NEW','field':'x','rule':'x >= 1','rule_type':'threshold','hit_count':1,'bad_count':1,'coverage':.5,'bad_rate':1.0,'base_bad_rate':.5,'lift':2.0,'bootstrap_positive_ratio':1.0,'grade':'A','is_representative':True,'reason':'test'}
    write_outputs(pd.DataFrame([{'field':'x'}]),[rule],df,str(tmp_path))
    assert '风控策略挖掘报告' in (tmp_path/'rule_report.md').read_text(encoding='utf-8')
    exported=pd.read_csv(tmp_path/'candidate_rules.csv')
    assert exported.loc[0,'rule_id']=='NEW_R000001'
