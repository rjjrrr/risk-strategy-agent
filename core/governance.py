import pandas as pd
from . import config
from .utils import normalize_missing, rate, safe_name
from .type_detector import detect_type
from .semantic_governance import semantic_class

def govern(df, target="target7", segment_field="is_old"):
    rows = []; clean = df.copy()
    for col in df.columns:
        s = normalize_missing(df[col]); clean[col] = s
        valid = s.notna(); n = len(s); vc = int(valid.sum()); u = int(s[valid].nunique())
        top1 = rate(s[valid].value_counts().iloc[0], vc) if vc else 0
        ur = rate(u, vc); vr = rate(vc, n); miss = 1 - vr
        name = safe_name(col); semantic_type, semantic_reason = semantic_class(col, s, ur); decision, reason = "KEEP", "通过基础治理"
        if col == target or col == segment_field: decision, reason = "SPECIAL", "业务关键字段"
        elif semantic_type == "EXISTING_MODEL": decision, reason = "SPECIAL", "SPECIAL_EXISTING_MODEL"
        elif semantic_type in ("TARGET_LEAKAGE", "POST_LOAN_FEATURE", "SUSPECT_LEAKAGE"): decision, reason = "SUSPECT_LEAKAGE", semantic_reason
        elif semantic_type == "IDENTIFIER": decision, reason = "EXCLUDE", semantic_reason
        elif name in config.ID_NAMES: decision, reason = "EXCLUDE", "标识字段"
        elif vr < config.MIN_VALID_RATE: decision, reason = "EXCLUDE", "有效覆盖率低于阈值"
        elif u <= 1: decision, reason = "EXCLUDE", "只有一个有效值"
        elif top1 > config.TOP1_RATIO_MAX: decision, reason = "EXCLUDE", "Top1占比过高"
        elif semantic_type in ("HIGH_CARD_IDENTIFIER",) or (ur >= config.UNIQUE_RATIO_ID and (name.endswith("_id") or any(t in name for t in config.IDENTIFIER_TOKENS))): decision, reason = "SPECIAL", "DERIVATION_RECOMMENDED: 高基数标识型字段"
        dtype = detect_type(s, decision)
        rows.append(dict(field=col, semantic_type=semantic_type, detected_type=dtype, valid_count=vc, valid_rate=vr, missing_count=n-vc, missing_rate=miss, unique_count=u, unique_ratio=ur, top1_ratio=top1, decision=decision, original_decision=decision, reason=reason))
    return clean, pd.DataFrame(rows)
