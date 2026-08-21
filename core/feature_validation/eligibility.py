from __future__ import annotations


def determine_eligibility(feature: dict, metrics: dict, decision: str) -> tuple[bool, bool, dict[str, list[str]]]:
    warnings = set(metrics.get("warnings", []))
    hard_block = bool(warnings & {"CONFIRMED_LEAKAGE", "RAW_DATETIME", "ID_LIKE", "INVALID_FEATURE", "EXTREME_DRIFT"})
    lgbm_reasons = []
    lr_reasons = []
    lgbm = decision in {"PROMISING", "EXPLORATORY", "REVIEW"} and not hard_block and metrics.get("missing_rate", 1) < 0.8
    if lgbm:
        lgbm_reasons.append("VALID_FOR_NONLINEAR_EXPERIMENT")
    else:
        lgbm_reasons.extend(sorted(warnings) or ["VALIDATION_REJECTED"])
    interpretable = bool(feature.get("human_formula") or feature.get("business_intent"))
    lr = (
        decision == "PROMISING"
        and not hard_block
        and metrics.get("psi", 1) < 0.1
        and metrics.get("max_existing_correlation", 1) < 0.95
        and metrics.get("iv", 0) >= 0.01
        and interpretable
    )
    if lr:
        lr_reasons.extend(["STABLE", "INTERPRETABLE", "USEFUL_IV", "ACCEPTABLE_CORRELATION"])
    else:
        if decision != "PROMISING": lr_reasons.append("NOT_PROMISING")
        if metrics.get("psi", 1) >= 0.1: lr_reasons.append("PSI_NOT_STABLE")
        if metrics.get("max_existing_correlation", 1) >= 0.95: lr_reasons.append("HIGH_REDUNDANCY")
        if metrics.get("iv", 0) < 0.01: lr_reasons.append("WEAK_IV")
        if not interpretable: lr_reasons.append("NOT_INTERPRETABLE")
        lr_reasons.extend(sorted(warnings & {"CONFIRMED_LEAKAGE", "RAW_DATETIME", "ID_LIKE", "INVALID_FEATURE", "EXTREME_DRIFT"}))
    return lr, lgbm, {"LR": sorted(set(lr_reasons)), "LGBM": sorted(set(lgbm_reasons))}
