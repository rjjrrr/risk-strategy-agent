from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


DOMAIN_TOKENS = {
    "IDENTITY": ("name", "gender", "age", "identity", "passport", "national"),
    "DEMOGRAPHIC": ("marital", "education", "occupation", "family"),
    "DEVICE": ("device", "imei", "oaid", "android", "phone_model"),
    "APP_BEHAVIOR": ("app_", "installed", "application_count"),
    "APPLICATION_BEHAVIOR": ("query", "apply", "application", "request"),
    "CREDIT": ("credit", "bureau", "loan_count", "debt"),
    "LOAN": ("loan", "amount", "term"),
    "REPAYMENT_CAPACITY": ("income", "salary", "cashflow", "capacity"),
    "INCOME": ("income", "salary", "wage"),
    "LOCATION": ("province", "city", "region", "location", "address"),
    "NETWORK": ("network", "ip", "wifi", "sharing"),
    "TIME": ("time", "date", "hour", "weekday"),
    "EXISTING_SCORE": ("score", "probability", "prediction"),
    "RULE_SIGNAL": ("rule_group", "rule_hit"),
}


class SemanticAnalysisAgent:
    def _domain(self, field: str, semantic_type: str) -> tuple[str, str, str]:
        name = field.lower()
        if semantic_type in {"IDENTIFIER", "DATETIME", "EXISTING_MODEL", "POST_LOAN_FEATURE", "SUSPECT_LEAKAGE"}:
            mapping = {"DATETIME": "TIME", "EXISTING_MODEL": "EXISTING_SCORE", "POST_LOAN_FEATURE": "LOAN", "SUSPECT_LEAKAGE": "LOAN"}
            return mapping.get(semantic_type, "IDENTITY"), "HIGH", f"governance semantic_type={semantic_type}"
        hits = [domain for domain, tokens in DOMAIN_TOKENS.items() if any(token in name for token in tokens)]
        if len(hits) == 1:
            return hits[0], "HIGH", "field-name semantic token matched"
        if len(hits) > 1:
            return hits[0], "MEDIUM", f"multiple semantic domains matched: {hits}"
        return "UNKNOWN", "LOW", "no reliable semantic token or description"

    def analyze(
        self, df: pd.DataFrame, governance: pd.DataFrame,
        rule_findings: list[dict[str, Any]] | None = None,
        descriptions: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        rules = rule_findings or []
        descriptions = descriptions or {}
        output = []
        for _, meta in governance.iterrows():
            field = str(meta["field"])
            if field not in df.columns:
                continue
            series = df[field]
            semantic_type = str(meta.get("semantic_type", "NORMAL_FEATURE"))
            domain, confidence, reason = self._domain(field, semantic_type)
            numeric = pd.api.types.is_numeric_dtype(series)
            allowed = ["RAW"]
            if confidence != "LOW" and semantic_type not in {"DATETIME", "IDENTIFIER", "POST_LOAN_FEATURE", "SUSPECT_LEAKAGE", "EXISTING_MODEL"}:
                allowed += ["COUNT", "FREQUENCY"]
                if numeric:
                    allowed += ["RATIO", "DIFFERENCE", "SHORT_LONG_RATIO"]
                if domain == "TIME":
                    allowed += ["TIME_WINDOW"]
            forbidden = ["TARGET_ENCODING", "ARBITRARY_CROSS", "POLYNOMIAL"]
            if confidence == "LOW":
                forbidden += ["RATIO", "DIFFERENCE", "CROSS_FIELD_TRANSFORMATION"]
            if semantic_type in {"DATETIME", "IDENTIFIER", "POST_LOAN_FEATURE", "SUSPECT_LEAKAGE", "EXISTING_MODEL"}:
                forbidden += ["MODEL_INPUT_RAW"]
            sample = series.dropna().head(5).tolist()
            sample = [value.item() if isinstance(value, np.generic) else str(value) if isinstance(value, pd.Timestamp) else value for value in sample]
            output.append({
                "field": field, "business_meaning": descriptions.get(field, field.replace("_", " ")),
                "semantic_role": semantic_type, "risk_domain": domain, "semantic_group": domain,
                "possible_relations": [], "allowed_feature_ops": sorted(set(allowed)),
                "forbidden_feature_ops": sorted(set(forbidden)), "confidence": confidence,
                "reason": reason, "dtype": str(series.dtype), "sample_values": sample,
                "missing_rate": float(series.isna().mean()), "unique_count": int(series.nunique(dropna=True)),
                "quantiles_or_categories": (
                    series.quantile([.1, .5, .9]).dropna().to_dict() if numeric
                    else series.value_counts(dropna=True).head(5).to_dict()
                ),
                "governance_decision": str(meta.get("decision", "REVIEW")),
                "existing_description": descriptions.get(field),
                "rule_mining_findings": [r.get("rule_id") for r in rules if r.get("field") == field],
            })
        return output
