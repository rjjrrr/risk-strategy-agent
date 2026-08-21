import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app import config
from backend.app.main import app
from backend.app.services import agent_chat_service, analysis_service, context_service
from core.analysis_state import new_state
from core.context import ContextBuilder, ContextItem, ContextRequest
from core.llm.bindings import BindingStore
from core.llm.prompts import PromptRegistry
from core.llm.runtime import LLMRuntime
from core.llm.runtime import _json_object
from core.llm.schemas import LLMBindingInput
from core.llm.storage import ChatStore


@pytest.fixture
def phase2(tmp_path, monkeypatch):
    did = "phase2-dataset"
    df = pd.DataFrame({
        "__row_id__": range(6), "target7": [1, 0, 1, 0, 1, 0], "is_old": [0, 0, 0, 2, 2, 2],
        "query_cnt_7d": [12, 1, 9, 99, 88, 77], "query_cnt_90d": [20, 5, 18, 100, 90, 80],
        "application_time": pd.date_range("2026-01-01", periods=6), "overdue_days": [0, 0, 0, 30, 20, 10],
    })
    state = new_state(did, "phase2.csv", len(df), len(df.columns))
    state["stages"]["rule_groups"] = {"summaries": [{"rule_group_id": "G_NEW", "segment": "NEW", "representative_field": "query_cnt_7d", "representative_rule": "query_cnt_7d > 8", "rule_count": 2, "average_jaccard": .94}, {"rule_group_id": "G_OLD", "segment": "OLD", "representative_field": "query_cnt_7d"}]}
    gov = pd.DataFrame([
        {"field": "query_cnt_7d", "semantic_type": "NORMAL_FEATURE", "detected_type": "numeric_count", "decision": "KEEP", "reason": "ok"},
        {"field": "query_cnt_90d", "semantic_type": "NORMAL_FEATURE", "detected_type": "numeric_count", "decision": "KEEP", "reason": "ok"},
        {"field": "application_time", "semantic_type": "DATETIME", "detected_type": "datetime", "decision": "KEEP", "reason": "derive first"},
        {"field": "overdue_days", "semantic_type": "SUSPECT_LEAKAGE", "detected_type": "numeric_count", "decision": "SUSPECT_LEAKAGE", "reason": "post performance"},
    ])
    analysis_service.DATASETS[did] = {"df": df, "governance": gov, "rules": [{"rule_id": "R_NEW", "segment": "NEW", "field": "query_cnt_7d", "rule": "query_cnt_7d > 8", "lift": 1.8, "grade": "A"}, {"rule_id": "R_OLD", "segment": "OLD", "field": "query_cnt_7d", "rule": "query_cnt_7d > 70", "lift": 2.0, "grade": "A"}], "target": "target7", "segment_field": "is_old", "state": state}
    db = tmp_path / "chat.sqlite3"; bs = BindingStore(db); ps = PromptRegistry(db); cs = ChatStore(db)
    monkeypatch.setattr(agent_chat_service, "bindings", bs); monkeypatch.setattr(agent_chat_service, "prompts", ps); monkeypatch.setattr(agent_chat_service, "store", cs); monkeypatch.setattr(agent_chat_service, "runtime", LLMRuntime(bs, ps))
    monkeypatch.setattr(config, "MODEL_AGENT_DIR", tmp_path / "models"); monkeypatch.setattr(context_service, "CONTEXT_DIR", tmp_path / "contexts"); context_service.CONTEXT_DIR.mkdir(); context_service._cache.clear()
    binding = bs.create(LLMBindingInput(display_name="mock", provider="MOCK", model="mock-v1", is_default=True))
    conversation = cs.create_conversation(agent_type="ANALYSIS_AGENT", default_binding_id=binding["binding_id"], dataset_id=did)
    yield did, cs, binding, conversation, tmp_path
    analysis_service.DATASETS.pop(did, None)


def test_context_message_explosion_budget_and_valid_json():
    request = ContextRequest(conversation_id="c", dataset_id="d", max_context_tokens=8000, max_items_per_source=100, focus_fields=["focus_field"], user_query="focus_field risk")
    types = list(ContextItem.model_fields["source_type"].annotation.__args__)
    items = [ContextItem(source_type=source, source_id=f"{source}-{i}", title=f"{source} {i}", content={"field": "focus_field" if i == 99 else f"field_{i}", "detail": "x" * 180}, field_names=["focus_field"] if i == 99 else []) for source in types for i in range(100)]
    bundle = ContextBuilder().build(request, items)
    assert bundle.estimated_context_tokens <= 8000
    assert bundle.dropped_items > 0 and bundle.included_items > 0
    assert json.loads(bundle.text)["context_version"] == "context-builder-v2"
    assert "TRUNCATED" not in bundle.text


def test_structured_parser_accepts_json_code_fence():
    assert _json_object('```json\n{"ok": true}\n```') == {"ok": True}


def test_context_is_new_only_and_excludes_raw_rows(phase2):
    did, cs, _, conv, _ = phase2
    result = context_service.build(ContextRequest(conversation_id=conv["conversation_id"], dataset_id=did), cs)
    payload = json.loads(result.text); rules = [x for x in payload["items"] if x["source_type"] == "RULE_SUMMARY"]
    summary = next(x for x in payload["items"] if x["source_type"] == "DATASET_SUMMARY")
    assert summary["content"]["new_rows"] == 3 and summary["content"]["new_rate"] == .5
    assert {x["source_id"] for x in rules} == {"R_NEW"}
    assert "sample_values" not in result.text and "R_OLD" not in result.text


def test_context_api_preview_and_cache(phase2):
    did, _, _, conv, _ = phase2; client = TestClient(app); body = {"conversation_id": conv["conversation_id"], "dataset_id": did, "user_query": "query risk"}
    first = client.post("/api/context/build", json=body); second = client.post("/api/context/build", json=body)
    assert first.status_code == 200 and second.json()["cache_hit"] is True
    preview = client.get(f"/api/context/{first.json()['context_id']}/preview").json()
    assert preview["context_hash"] == first.json()["context_hash"] and preview["estimated_context_tokens"] <= 8000


def test_analysis_agent_structured_trace_and_proposals(phase2):
    did, _, binding, conv, _ = phase2; client = TestClient(app)
    response = client.post(f"/api/agent-chat/conversations/{conv['conversation_id']}/messages", json={"content": "Analyze NEW risk signals", "agent_type": "ANALYSIS_AGENT", "binding_id": binding["binding_id"]})
    assert response.status_code == 200
    body = response.json(); assert body["structured"]["analysis_summary"] and body["assistant_message"]["structured_output_status"] == "VALIDATED"
    assert body["trace"]["context_id"] and body["trace"]["context_items_count"] > 0 and body["trace"]["estimated_context_tokens"] <= 8000
    assert {x["proposal_type"] for x in body["proposals"]} == {"HYPOTHESIS_CREATE", "FEATURE_CANDIDATE"}


def test_feature_proposal_guards(phase2):
    did, _, _, _, tmp = phase2
    invalid = agent_chat_service._feature_validation(did, {"feature_name": "bad", "source_fields": ["missing"], "formula": "missing", "semantic_meaning": "x"})
    leakage = agent_chat_service._feature_validation(did, {"feature_name": "leak", "source_fields": ["overdue_days"], "formula": "overdue_days", "semantic_meaning": "x"})
    datetime = agent_chat_service._feature_validation(did, {"feature_name": "date", "feature_type": "RAW", "source_fields": ["application_time"], "formula": "application_time", "semantic_meaning": "x"})
    registry = FeatureRegistry(config.MODEL_AGENT_DIR / did)
    registry.add({"feature_id": "F_EXISTING", "feature_name": "ratio", "source_fields": ["query_cnt_7d", "query_cnt_90d"], "formula": "query_cnt_7d/query_cnt_90d", "calculation_description": "ratio"})
    duplicate = agent_chat_service._feature_validation(did, {"feature_name": "ratio2", "source_fields": ["query_cnt_90d", "query_cnt_7d"], "formula": "query_cnt_7d / query_cnt_90d", "semantic_meaning": "ratio"})
    assert invalid["validation_code"] == "INVALID_SOURCE_FIELD"
    assert leakage["validation_code"] == "LEAKAGE_RISK"
    assert datetime["validation_code"] == "DATETIME_RAW_FORBIDDEN"
    assert duplicate == {"validation_status": "DUPLICATE", "validation_code": "DUPLICATE_FEATURE", "existing_feature_id": "F_EXISTING"}


from core.model_agent.registry import FeatureRegistry
