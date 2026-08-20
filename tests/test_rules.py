import pandas as pd
from core.evaluator import evaluate

def test_extreme_and_missing_rule_review():
    df=pd.DataFrame({"__target__":[1]*20+[0]*20,"__segment__":["NEW"]*40,"x":[1]*20+[0]*20})
    r=evaluate(df.x==1,df,"fact_back_time","fact_back_time == __MISSING__","category","__MISSING__",semantic_type="POST_LOAN_FEATURE")
    assert r["status"] == "REVIEW"
    assert r["grade"] == "REVIEW"
    assert r["missing_rule"] is True
