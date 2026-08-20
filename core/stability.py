import numpy as np
from . import config
def bootstrap(rule_row, mask, segment_df):
    rng = np.random.default_rng(config.RANDOM_STATE); y = segment_df["__target__"].to_numpy(); m = mask.to_numpy(bool); n = len(y); lifts=[]
    for _ in range(config.BOOTSTRAP_N):
        ix = rng.integers(0, n, size=max(1, int(n*config.BOOTSTRAP_SAMPLE_RATE))); yy=y[ix]; mm=m[ix]
        base=yy.mean(); br=yy[mm].mean() if mm.any() else np.nan; lifts.append(br/base if base else np.nan)
    a=np.asarray(lifts, dtype=float); a=a[np.isfinite(a)]
    rule_row.update(bootstrap_mean_lift=float(a.mean()) if len(a) else np.nan, bootstrap_lift_std=float(a.std()) if len(a) else np.nan, bootstrap_positive_ratio=float(np.mean(a>=1.0)) if len(a) else 0.0)
    small = len(segment_df) < config.SMALL_SEGMENT_THRESHOLD
    rule_row["small_segment"] = small
    if rule_row.get("status") == "REVIEW":
        rule_row["grade"] = "REVIEW"
    elif rule_row["status"] == "PASS" and rule_row.get("grade") != "REVIEW":
        if (not small and rule_row["lift"] >= config.STRICT_A_LIFT and rule_row["hit_count"] >= config.STRICT_A_HIT_COUNT and rule_row["bad_count"] >= config.STRICT_A_BAD_COUNT and rule_row["coverage"] >= config.STRICT_A_COVERAGE and rule_row["bootstrap_positive_ratio"] >= config.STRICT_A_BOOTSTRAP and not rule_row.get("rare_category") and not rule_row.get("missing_rule") and not rule_row.get("warning")): rule_row["grade"]="A"
        elif (small and rule_row["lift"] >= 1.50 and rule_row["hit_count"] >= 30 and rule_row["bad_count"] >= 15 and rule_row["coverage"] >= .05 and rule_row["bootstrap_positive_ratio"] >= .95 and not rule_row.get("rare_category") and not rule_row.get("missing_rule") and not rule_row.get("warning")): rule_row["grade"]="A"
        elif rule_row["lift"] >= config.MIN_LIFT: rule_row["grade"]="B"
        else: rule_row["grade"]="C"
    if small and rule_row["grade"] == "A" and not (rule_row["lift"] >= 1.50 and rule_row["hit_count"] >= 30 and rule_row["bad_count"] >= 15 and rule_row["coverage"] >= .05 and rule_row["bootstrap_positive_ratio"] >= .95): rule_row["grade"]="B"
    if rule_row.get("grade") is None: rule_row["grade"]="C"
    return rule_row
