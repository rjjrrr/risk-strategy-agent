from __future__ import annotations


def feature_novelty(feature: dict, existing_features: list[dict], max_correlation: float) -> tuple[str, list[str]]:
    reasons = []
    normalized = feature.get("normalized_ast")
    sources = tuple(sorted(str(x) for x in feature.get("source_fields", [])))
    domain = feature.get("semantic_domain")
    for other in existing_features:
        if other.get("feature_id") == feature.get("feature_id"):
            continue
        if normalized and normalized == other.get("normalized_ast"):
            reasons.append("SAME_NORMALIZED_AST")
        if sources and sources == tuple(sorted(str(x) for x in other.get("source_fields", []))):
            reasons.append("SAME_SOURCE_FIELDS")
        if domain and domain == other.get("semantic_domain"):
            reasons.append("SAME_SEMANTIC_DOMAIN")
    if max_correlation >= 0.95:
        reasons.append("HIGH_CORRELATION")
    if "SAME_NORMALIZED_AST" in reasons or "HIGH_CORRELATION" in reasons:
        return "LOW", sorted(set(reasons))
    if max_correlation >= 0.8 or "SAME_SOURCE_FIELDS" in reasons:
        return "MEDIUM", sorted(set(reasons))
    return "HIGH", sorted(set(reasons))
