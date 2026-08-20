import pandas as pd
from core.governance import govern

def test_semantic_governance_cases():
    df=pd.DataFrame({"NgaFraud__phoneNumber":[7000000001,7000000002,None],"NgaFraud__maritalStatus":["single","married","single"],"fact_back_time":[None,None,"2024-01-01"],"risk_over_days":[1,2,0],"final_score":[.1,.2,.3],"target7":[0,1,0],"is_old":[0,0,2]})
    _,m=govern(df); row=m.set_index("field")
    assert row.loc["NgaFraud__phoneNumber","semantic_type"] == "IDENTIFIER"
    assert row.loc["NgaFraud__phoneNumber","decision"] == "EXCLUDE"
    assert row.loc["NgaFraud__maritalStatus","decision"] == "KEEP"
    assert row.loc["fact_back_time","semantic_type"] == "POST_LOAN_FEATURE"
    assert row.loc["risk_over_days","decision"] == "SUSPECT_LEAKAGE"
    assert row.loc["final_score","semantic_type"] == "EXISTING_MODEL"
