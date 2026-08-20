"""字段语义治理：用 token、值域和字段名共同判断贷前可用性。"""
import re
import pandas as pd
from . import config

def tokens(field):
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(field)).lower()
    return tuple(x for x in re.split(r"[^a-z0-9]+", raw) if x)

def semantic_class(field, series, unique_ratio=0.0):
    ts = set(tokens(field)); joined = "_".join(tokens(field))
    if field in ("target7", "target", "label"):
        return "TARGET", "业务目标变量，不参与规则挖掘"
    if any(x in joined or x in ts for x in config.MODEL_TOKENS):
        return "EXISTING_MODEL", "已有模型分/预测字段"
    if any(x in joined for x in config.POST_LOAN_TOKENS):
        return ("POST_LOAN_FEATURE", "字段语义可能来自贷后或结果时点")
    if any(x in joined for x in config.LEAKAGE_SUSPECT_TOKENS):
        return "SUSPECT_LEAKAGE", "变量语义可能直接包含逾期天数或贷后表现"
    if any(x in joined for x in config.IDENTIFIER_SEMANTIC_TOKENS):
        return "IDENTIFIER", "手机号、设备号、证件号或账户标识，不应作为连续变量扫描"
    if any(x in ts for x in ("time", "date", "datetime", "timestamp")) or any(x in joined for x in ("create_time", "update_time", "back_time", "repay_time", "finish_time", "approve_time", "disburse_time", "register_time", "first_seen_time")):
        if any(x in joined for x in ("fact_back", "repay", "settle", "collection", "close", "finish")):
            return "POST_LOAN_FEATURE", "结果时点或贷后时间字段"
        return "DATETIME", "时间字段，需经过时间差/窗口加工后使用"
    if unique_ratio >= config.UNIQUE_RATIO_ID and ("id" in ts or "uuid" in ts):
        return "HIGH_CARD_IDENTIFIER", "高唯一率标识字段"
    return "NORMAL_FEATURE", "可作为普通贷前变量评估"
