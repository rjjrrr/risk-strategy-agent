from __future__ import annotations

import uuid

import pandas as pd

from .correlation import correlations
from .eligibility import determine_eligibility
from .iv import information_value
from .metrics import distribution_summary, temporal_summary
from .novelty import feature_novelty
from .psi import population_stability_index, psi_label
from .schemas import FeatureValidationResult


class FeatureCheapValidator:
    def validate(
        self,
        *,
        feature: dict,
        values: pd.Series,
        target: pd.Series,
        dataset_id: str,
        dev_mask: pd.Series,
        oot_mask: pd.Series,
        times: pd.Series | None = None,
        existing_pool: pd.DataFrame | None = None,
        existing_registry: list[dict] | None = None,
        governance: dict | None = None,
    ) -> FeatureValidationResult:
        values = pd.Series(values, index=target.index)
        valid = values.notna() & target.isin([0, 1])
        distribution, bad_pattern, warnings = distribution_summary(values, target)
        corr = correlations(values, target, existing_pool)
        psi = population_stability_index(values[dev_mask], values[oot_mask])
        periods, temporal_warnings = temporal_summary(values, target, times)
        warnings.extend(temporal_warnings)
        governance = governance or {}
        if any(governance.get(field, {}).get("decision") == "SUSPECT_LEAKAGE" for field in feature.get("source_fields", [])):
            warnings.append("CONFIRMED_LEAKAGE")
        if feature.get("feature_type") == "RAW" and feature.get("semantic_domain") == "TIME":
            warnings.append("RAW_DATETIME")
        unique_count = int(values[valid].nunique(dropna=True))
        unique_rate = unique_count / int(valid.sum()) if valid.any() else 0.0
        if unique_rate > 0.98 and unique_count > 100 and (feature.get("feature_type") == "RAW" or feature.get("semantic_domain") == "ID"):
            warnings.append("ID_LIKE")
        if psi >= 0.25:
            warnings.append("EXTREME_DRIFT")
        novelty, novelty_reasons = feature_novelty(feature, existing_registry or [], corr["max_existing_correlation"])
        metrics = {
            "row_count": int(len(values)), "valid_count": int(valid.sum()), "valid_rate": float(valid.mean()),
            "missing_count": int(values.isna().sum()), "missing_rate": float(values.isna().mean()),
            "unique_count": unique_count, "unique_rate": unique_rate, "distribution_summary": distribution,
            "bad_rate_pattern": bad_pattern, "lift": bad_pattern.get("max_lift"),
            "iv": information_value(values, target), "psi": psi, "psi_status": psi_label(psi),
            "temporal_stability": periods, **corr, "feature_novelty": novelty,
            "novelty_reasons": novelty_reasons, "warnings": sorted(set(warnings)),
        }
        lift = metrics.get("lift") or 0.0
        hard_reject = bool(set(warnings) & {"CONFIRMED_LEAKAGE", "RAW_DATETIME", "ID_LIKE", "INVALID_FEATURE"}) or metrics["valid_rate"] < 0.2 or unique_count <= 1
        if "SIGN_FLIP" in warnings and lift >= 1.2 and metrics["iv"] >= 0.02:
            hard_reject = True
        if hard_reject:
            decision = "REJECTED"
        elif psi >= 0.25:
            decision = "REVIEW"
        elif metrics["valid_rate"] < 0.5 or corr["max_existing_correlation"] >= 0.95:
            decision = "REVIEW"
        elif lift >= 1.2 and metrics["iv"] >= 0.01 and psi < 0.1 and novelty != "LOW":
            decision = "PROMISING"
        elif novelty == "HIGH" and psi < 0.1:
            decision = "EXPLORATORY"
        else:
            decision = "REVIEW"
        lr, lgbm, reasons = determine_eligibility(feature, metrics, decision)
        return FeatureValidationResult(
            validation_id=f"FV_{uuid.uuid4().hex[:12]}", feature_id=feature["feature_id"],
            feature_version=str(feature.get("version") or feature.get("feature_version") or "1.0"),
            dataset_id=dataset_id, metrics=metrics, decision=decision, lr_eligible=lr,
            lgbm_eligible=lgbm, eligibility_reasons=reasons, warnings=sorted(set(warnings)),
        )
