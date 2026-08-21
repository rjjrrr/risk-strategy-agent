from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from core.context import ContextBuilder, ContextBundle, ContextRequest
from core.context.serialization import content_hash
from core.context.sources import item
from core.json_utils import sanitize_json
from .. import config
from .analysis_service import DATASETS

CONTEXT_DIR = config.RUNTIME_DIR / "contexts"
CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
_builder = ContextBuilder()
_cache: dict[str, str] = {}


def _json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (ValueError, OSError):
        return default


def _new_frame(ds: dict[str, Any]) -> pd.DataFrame:
    df = ds["df"]
    segment = ds.get("segment_field") or ds.get("state", {}).get("config", {}).get("segment_field", "is_old")
    if segment not in df:
        return df.iloc[0:0]
    return df[df[segment].map(lambda x: "NEW" if x == 0 or str(x).upper() == "NEW" else "OLD") == "NEW"]


def _governance_rows(ds: dict[str, Any]) -> list[dict[str, Any]]:
    gov = ds.get("governance")
    if gov is None:
        return []
    if hasattr(gov, "to_dict"):
        return sanitize_json(gov.to_dict("records"))
    return sanitize_json(gov)


def _conversation_items(store: Any, request: ContextRequest) -> list[Any]:
    if not request.include_conversation_memory:
        return []
    messages = [m for m in store.messages(request.conversation_id) if m.get("role") in {"user", "assistant"} and m.get("status") in {"SUCCESS", "CANCELLED"}]
    older, recent = messages[:-8], messages[-8:]
    terms = Counter()
    for message in older:
        for token in str(message.get("content", "")).lower().replace("，", " ").replace(",", " ").split():
            if 2 <= len(token) <= 40:
                terms[token] += 1
    result = []
    if older:
        result.append(item("CONVERSATION_MEMORY", "summary", "Earlier conversation summary", {
            "message_count": len(older), "roles": dict(Counter(x["role"] for x in older)),
            "frequent_terms": [x for x, _ in terms.most_common(12)],
            "note": "Deterministic extract; earlier message bodies omitted.",
        }, priority="LOW"))
    for message in recent:
        result.append(item("CONVERSATION_MEMORY", message["message_id"], f"Recent {message['role']} message", {
            "role": message["role"], "content": str(message.get("content", ""))[:800], "status": message.get("status"),
        }, priority="LOW", created_at=message.get("created_at")))
    return result


def collect(request: ContextRequest, store: Any) -> list[Any]:
    if request.dataset_id not in DATASETS:
        raise KeyError(f"Dataset not loaded: {request.dataset_id}")
    ds = DATASETS[request.dataset_id]; df = ds["df"]; new = _new_frame(ds)
    target = ds.get("target") or ds.get("state", {}).get("config", {}).get("target", "target7")
    rows: list[Any] = []
    if request.include_dataset_summary:
        rows.append(item("DATASET_SUMMARY", request.dataset_id, "NEW dataset summary", {
            "scope": "NEW_ONLY", "total_rows": len(df), "new_rows": len(new), "new_rate": len(new) / len(df) if len(df) else 0,
            "column_count": len(df.columns), "target": target,
            "new_bad_rate": float(pd.to_numeric(new[target], errors="coerce").mean()) if target in new and len(new) else None,
            "fields": [str(x) for x in df.columns if x != "__row_id__"],
        }, priority="CRITICAL"))
    if request.include_data_health:
        rows.append(item("DATA_HEALTH", request.dataset_id, "NEW data health", {
            "scope": "NEW_ONLY", "row_count": len(new), "duplicate_rows": int(new.drop(columns=["__row_id__"], errors="ignore").duplicated().sum()),
            "columns_with_missing": int((new.isna().mean() > 0).sum()), "max_missing_rate": float(new.isna().mean().max()) if len(new.columns) else 0,
            "constant_columns": [str(c) for c in new.columns if new[c].nunique(dropna=True) <= 1][:30],
        }, priority="HIGH"))
    governance = _governance_rows(ds)
    if request.include_governance:
        for row in governance:
            field = str(row.get("field", ""))
            rows.append(item("GOVERNANCE", field, f"Governance: {field}", {k: row.get(k) for k in ("semantic_type", "detected_type", "decision", "reason", "missing_rate", "unique_count")}, priority="CRITICAL" if row.get("decision") in {"SUSPECT_LEAKAGE", "EXCLUDE", "SPECIAL"} else "MEDIUM", fields=[field]))
    if request.include_variable_profiles:
        gov_by_field = {str(x.get("field")): x for x in governance}
        for field in [str(x) for x in df.columns if x != "__row_id__"]:
            series = new[field]
            numeric = pd.to_numeric(series, errors="coerce")
            content = {"scope": "NEW_ONLY", "dtype": str(series.dtype), "count": int(series.notna().sum()), "missing_rate": float(series.isna().mean()) if len(series) else None, "unique_count": int(series.nunique(dropna=True)), "governance_decision": gov_by_field.get(field, {}).get("decision")}
            if numeric.notna().sum() >= max(2, int(series.notna().sum() * .5)):
                content["numeric_summary"] = {k: float(v) for k, v in numeric.describe(percentiles=[.05, .5, .95]).items() if pd.notna(v)}
            else:
                content["top_value_rates"] = {str(k): float(v / len(series)) for k, v in series.value_counts(dropna=False).head(5).items()} if len(series) else {}
            rows.append(item("VARIABLE_PROFILE", field, f"NEW profile: {field}", content, fields=[field]))
    rules = [r for r in ds.get("rules", []) if str(r.get("segment", "")).upper() == "NEW"]
    if request.include_rules:
        for rule in rules:
            field = str(rule.get("field", "")); rid = str(rule.get("rule_id") or content_hash({"field": field, "rule": rule.get("rule")})[:12])
            rows.append(item("RULE_SUMMARY", rid, f"Rule {rid}: {rule.get('rule')}", {k: rule.get(k) for k in ("rule_id", "field", "rule", "rule_type", "hit_count", "coverage", "bad_rate", "base_bad_rate", "lift", "grade", "oot_status", "bootstrap_positive_ratio", "rule_group_id")}, priority="HIGH" if rule.get("grade") in {"A", "B"} else "MEDIUM", fields=[field]))
    if request.include_rule_groups:
        groups = ds.get("state", {}).get("stages", {}).get("rule_groups", {}).get("summaries", [])
        for group in groups:
            if str(group.get("segment", "")).upper() != "NEW": continue
            field = str(group.get("representative_field", "")); gid = str(group.get("rule_group_id"))
            rows.append(item("RULE_GROUP", gid, f"NEW rule group {gid}", {k: group.get(k) for k in ("rule_group_id", "representative_rule_id", "representative_field", "representative_rule", "rule_count", "average_jaccard", "representative_hit_count", "representative_bad_rate", "representative_lift", "representative_coverage", "oot_status", "cluster_quality", "warning")}, priority="HIGH", fields=[field]))
    root = config.MODEL_AGENT_DIR / request.dataset_id
    registry_specs = [
        (request.include_features, "FEATURE_REGISTRY", "feature_registry.json", "feature_id", "feature_name"),
        (request.include_hypotheses, "HYPOTHESIS_REGISTRY", "hypothesis_registry.json", "hypothesis_id", "risk_mechanism"),
        (request.include_experiments, "EXPERIMENT_HISTORY", "experiment_registry.json", "experiment_id", "description"),
    ]
    for enabled, source_type, filename, id_key, title_key in registry_specs:
        if not enabled: continue
        for row in _json(root / filename, []):
            fields = [str(x) for x in row.get("source_fields", [])]
            rows.append(item(source_type, row.get(id_key, content_hash(row)[:12]), f"{source_type}: {row.get(title_key) or row.get(id_key)}", sanitize_json(row), priority="HIGH" if row.get("status") in {"PROPOSED", "APPROVED"} else "MEDIUM", fields=fields, created_at=row.get("updated_at") or row.get("created_at")))
    if request.include_model_state:
        state = _json(root / "model_agent_state.json", {})
        if state:
            rows.append(item("MODEL_STATE", state.get("current_state_id", "current"), "Current model state", sanitize_json(state), priority="HIGH"))
    rows.extend(_conversation_items(store, request))
    return rows


def build(request: ContextRequest, store: Any) -> ContextBundle:
    source_items = collect(request, store)
    cache_key = content_hash({"request": request.model_dump(), "sources": [x.model_dump() for x in source_items]})
    cached_id = _cache.get(cache_key)
    if cached_id:
        cached = load(cached_id)
        if cached:
            cached.cache_hit = True
            return cached
    bundle = _builder.build(request, source_items)
    path = CONTEXT_DIR / f"{bundle.context_id}.json"
    path.write_text(json.dumps(sanitize_json(bundle.model_dump(exclude={"text"})), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (CONTEXT_DIR / f"{bundle.context_id}.context.json").write_text(bundle.text, encoding="utf-8")
    _cache[cache_key] = bundle.context_id
    return bundle


def load(context_id: str) -> ContextBundle | None:
    meta = CONTEXT_DIR / f"{context_id}.json"; content = CONTEXT_DIR / f"{context_id}.context.json"
    if not meta.exists() or not content.exists():
        return None
    data = _json(meta, {}); data["text"] = content.read_text(encoding="utf-8")
    return ContextBundle.model_validate(data)


def preview(context_id: str) -> dict[str, Any] | None:
    bundle = load(context_id)
    if not bundle:
        return None
    return {"context_id": bundle.context_id, "context_hash": bundle.context_hash, "estimated_context_tokens": bundle.estimated_context_tokens, "included_items": bundle.included_items, "dropped_items": bundle.dropped_items, "deduplicated_items": bundle.deduplicated_items, "sources_used": bundle.sources_used, "source_counts": bundle.source_counts, "versions": bundle.versions, "items": [{"source_type": x.source_type, "source_id": x.source_id, "title": x.title, "priority": x.priority, "relevance_score": x.relevance_score, "field_names": x.field_names} for x in bundle.items]}
