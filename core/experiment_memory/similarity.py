from __future__ import annotations


def similarity_score(query: dict, row: dict) -> float:
    score = 0.0
    if query.get("dataset_id") == row.get("dataset_id"): score += 4.0
    if query.get("dataset_version") and query.get("dataset_version") == row.get("dataset_version"): score += 1.0
    if query.get("model_type") == row.get("model_type"): score += 2.0
    if query.get("diagnosis_type") == row.get("diagnosis_before"): score += 1.0
    if set(query.get("feature_types") or [query.get("feature_type")]) & set(row.get("feature_types") or []): score += 2.0
    if set(query.get("semantic_domains") or [query.get("semantic_domain")]) & set(row.get("semantic_domains") or []): score += 2.0
    return score
