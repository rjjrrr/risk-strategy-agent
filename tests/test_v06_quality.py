import numpy as np
import pandas as pd
from core.evaluator import evaluate
from core.rule_deduplicator import deduplicate

def test_other_rare_is_review():
    df=pd.DataFrame({'__target__':[1,1,0,0,0,0],'__segment__':['NEW']*6})
    row=evaluate(pd.Series([True,True,False,False,False,False]),df,'maritalStatus','maritalStatus == __OTHER_RARE__','category','__OTHER_RARE__',semantic_type='NORMAL_FEATURE')
    assert row['status']=='REVIEW'
    assert row['grade']=='REVIEW'
    assert row['warning']=='RARE_CATEGORY_WARNING'

def test_jaccard_rule_group_marks_one_representative():
    rules=[
        {'segment':'NEW','field':'x','grade':'B','lift':1.3,'hit_count':80,'coverage':.4,'bootstrap_positive_ratio':.9,'_mask':np.array([1,1,1,1,0,0],dtype=bool)},
        {'segment':'NEW','field':'y','grade':'B','lift':1.2,'hit_count':81,'coverage':.4,'bootstrap_positive_ratio':.9,'_mask':np.array([1,1,1,1,0,0],dtype=bool)},
    ]
    out=deduplicate(rules)
    assert out[0]['rule_group_id']==out[1]['rule_group_id']
    assert sum(x['is_representative'] for x in out)==1
