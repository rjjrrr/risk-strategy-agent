"""Run the Phase 2 real-data + real-Zhipu acceptance check.

Requires ZHIPU_API_KEY in the process environment. Generated evidence is stored
under ignored test_artifacts/phase2_acceptance and never contains the secret.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services import agent_chat_service, analysis_service, context_service
from core.json_utils import sanitize_json
from core.llm.bindings import BindingStore
from core.llm.prompts import PromptRegistry
from core.llm.runtime import LLMRuntime
from core.llm.schemas import LLMBindingInput
from core.llm.storage import ChatStore


def main() -> None:
    key = os.getenv("ZHIPU_API_KEY")
    if not key:
        raise SystemExit("ZHIPU_API_KEY is required")
    out = ROOT / "test_artifacts" / "phase2_acceptance"; out.mkdir(parents=True, exist_ok=True)
    source = ROOT / "test_artifacts" / "large_regression" / "01_mineable" / "source.csv"
    did, _ = analysis_service.register_upload(source.name, source.read_bytes())
    analysis_service.run_all(did, force=True)
    db = out / "acceptance.sqlite3"; db.unlink(missing_ok=True)
    bindings = BindingStore(db); prompts = PromptRegistry(db); store = ChatStore(db)
    binding = bindings.create(LLMBindingInput(display_name="Phase2 Zhipu", provider="ZHIPU_OPENAI_COMPATIBLE", base_url="https://open.bigmodel.cn/api/paas/v4", model="glm-4-plus", api_key=key, max_tokens=2200, timeout_seconds=60, is_default=True))
    agent_chat_service.bindings = bindings; agent_chat_service.prompts = prompts; agent_chat_service.store = store; agent_chat_service.runtime = LLMRuntime(bindings, prompts)
    context_service._cache.clear()
    conversation = store.create_conversation(title="Phase 2 real acceptance", agent_type="ANALYSIS_AGENT", default_binding_id=binding["binding_id"], dataset_id=did)
    result = agent_chat_service.send(conversation["conversation_id"], "请仅基于 NEW 客群的确定性上下文分析主要风险机制，给出至少 3 条有证据的假设和可审查特征建议；缺失的实验或模型信息必须明确披露。", "ANALYSIS_AGENT", binding["binding_id"], focus_fields=[])
    structured = result["structured"]
    evidence = {
        "dataset_id": did, "source": str(source.relative_to(ROOT)), "binding": {"provider": binding["provider"], "model": binding["model"]},
        "context": result["context"], "trace": {k: result["trace"].get(k) for k in ("call_id", "prompt_version", "runtime_type", "context_id", "input_context_hash", "context_items_count", "estimated_context_tokens", "sources_used", "prompt_tokens", "completion_tokens", "total_tokens", "success")},
        "structured": structured, "proposal_count": len(result["proposals"]),
        "proposal_validations": [{"type": x["proposal_type"], "title": x["title"], "validation": x["payload"].get("validation")} for x in result["proposals"]],
        "checks": {"new_only_context": "DATASET_SUMMARY" in result["context"]["sources_used"], "structured_valid": bool(structured), "hypotheses_at_least_3": len(structured.get("hypotheses", [])) >= 3, "within_budget": result["context"]["estimated_context_tokens"] <= 8000, "no_registry_execution": all(x["status"] == "PENDING" for x in result["proposals"])},
    }
    (out / "acceptance.json").write_text(json.dumps(sanitize_json(evidence), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"artifact": str((out / 'acceptance.json').relative_to(ROOT)), "checks": evidence["checks"], "hypotheses": len(structured.get("hypotheses", [])), "features": len(structured.get("feature_proposals", [])), "context_tokens": result["context"]["estimated_context_tokens"], "proposal_count": len(result["proposals"])}, ensure_ascii=False))
    if not all(evidence["checks"].values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
