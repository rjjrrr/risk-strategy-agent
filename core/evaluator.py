import numpy as np
from . import config
from .utils import rate

def evaluate(mask, segment_df, field, rule, rule_type, threshold=None, reason="", semantic_type="NORMAL_FEATURE"):
    y = segment_df["__target__"].astype(int); hit = mask.fillna(False)
    n, bad = int(hit.sum()), int(y[hit].sum()); total = len(y); base = rate(y.sum(), total)
    br = rate(bad, n); lift = rate(br, base)
    min_n = config.MIN_RULE_SAMPLE_OLD if segment_df["__segment__"].iloc[0] == "OLD" else config.MIN_RULE_SAMPLE_NEW
    coverage=rate(n,total); good_rate=rate(n-bad,n); missing_rule = threshold == "__MISSING__" or "__MISSING__" in str(rule)
    extreme = (br >= config.EXTREME_BAD_RATE if br == br else False) or (good_rate >= config.EXTREME_GOOD_RATE if good_rate == good_rate else False) or (lift >= config.EXTREME_LIFT if lift == lift else False)
    risky_missing = missing_rule and semantic_type in ("DATETIME", "POST_LOAN_FEATURE", "SUSPECT_LEAKAGE")
    ok = n >= min_n and bad >= config.MIN_BAD_COUNT and coverage >= config.MIN_RULE_COVERAGE and lift >= config.MIN_LIFT
    review_reason = ""
    if extreme or risky_missing:
        review_reason = "异常强相关，疑似目标泄露，请人工确认字段血缘。"
    rare_category = threshold == "__OTHER_RARE__" or "__OTHER_RARE__" in str(rule)
    if rare_category:
        review_reason = "低频类别合并为 OTHER_RARE，需人工确认类别业务含义。"
    review = bool(review_reason)
    if missing_rule and semantic_type in ("DATETIME", "POST_LOAN_FEATURE", "SUSPECT_LEAKAGE"):
        ok = False; review = True
    grade = "REVIEW" if review else (None if ok else "C")
    warning = "RARE_CATEGORY_WARNING" if rare_category else ("EXTREME_RULE_WARNING" if extreme else "")
    return dict(field=field, rule=rule, rule_type=rule_type, threshold_or_category=threshold, hit_count=n, bad_count=bad, good_count=n-bad, coverage=coverage, bad_rate=br, base_bad_rate=base, lift=lift, status="REVIEW" if review else ("PASS" if ok else "REJECT"), reason=reason, semantic_type=semantic_type, missing_rule=missing_rule, rare_category=rare_category, warning=warning, review_reason=review_reason, grade=grade)
