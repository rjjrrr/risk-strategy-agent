from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from core.counterfactual.audit import CounterfactualRegistry, FeatureCreditRegistry, HypothesisCreditRegistry
from core.experiment_memory.aggregator import CreditAggregator
from core.experiment_memory.audit import AggregateCreditRegistry, ExperimentMemoryRegistry
from core.experiment_memory.builder import ExperimentMemoryBuilder
from core.experiment_memory.retriever import ExperimentRetriever
from core.feature_validation.audit import FeatureValidationRegistry
from core.model_agent.registry import ExperimentRegistry, FeatureRegistry, HypothesisRegistry
from core.surrogate.audit import SurrogateRegistry
from core.surrogate.ranking import CandidateRanker
from core.surrogate.trainer import SurrogateTrainer
from core.surrogate.diagnostics import audit_dataset, compare_models, feature_group_ablation

from .. import config


def root(dataset_id: str) -> Path:
    path = config.MODEL_AGENT_DIR / dataset_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def memory_root(dataset_id: str) -> Path:
    path = root(dataset_id) / "experiment_memory"
    path.mkdir(parents=True, exist_ok=True)
    return path


def dataset_version(dataset_id: str) -> str:
    state_path = root(dataset_id) / "model_agent_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    explicit = state.get("dataset_version") or state.get("config", {}).get("dataset_version")
    return str(explicit or hashlib.sha256(dataset_id.encode()).hexdigest()[:12])


def refresh(dataset_id: str) -> dict[str, Any]:
    started = time.perf_counter(); model_root = root(dataset_id); mem_root = memory_root(dataset_id)
    experiments = CounterfactualRegistry(model_root).all()
    # Older model-agent experiments are retained when they are not already represented.
    known = {x.get("experiment_id") for x in experiments}
    experiments += [x for x in ExperimentRegistry(model_root).all() if x.get("experiment_id") not in known]
    registry = ExperimentMemoryRegistry(mem_root)
    result = ExperimentMemoryBuilder(registry).build(
        experiments, dataset_id=dataset_id, dataset_version=dataset_version(dataset_id),
        features=FeatureRegistry(model_root).all(), hypotheses=HypothesisRegistry(model_root).all(),
        validations=FeatureValidationRegistry(model_root).all(), feature_credits=FeatureCreditRegistry(model_root).all(),
        hypothesis_credits=HypothesisCreditRegistry(model_root).all(), source="REAL",
    )
    rows = registry.all(); aggregate_started = time.perf_counter()
    credits = CreditAggregator().all_dimensions(rows, dataset_id=dataset_id)
    flat = [item for group in credits.values() for item in group]
    AggregateCreditRegistry(mem_root).replace(flat)
    return {**result, "credits": credits, "performance_ms": {"memory_build": round((aggregate_started-started)*1000, 3), "aggregate_credit": round((time.perf_counter()-aggregate_started)*1000, 3)}}


def summary(dataset_id: str) -> dict[str, Any]:
    refreshed = refresh(dataset_id); rows = ExperimentMemoryRegistry(memory_root(dataset_id)).all()
    counts = {key: sum(x.get("counterfactual_decision") == key for x in rows) for key in ("POSITIVE", "NEUTRAL", "NEGATIVE", "UNSTABLE", "FAILED")}
    models = SurrogateRegistry(memory_root(dataset_id) / "surrogate").all()
    return {"dataset_id": dataset_id, "dataset_version": dataset_version(dataset_id), "total_experiments": len(rows), "outcomes": counts, "credits": refreshed["credits"], "surrogate": models[-1] if models else {"status": "INSUFFICIENT_DATA", "training_count": len(rows)}, "performance_ms": refreshed["performance_ms"]}


def similar(dataset_id: str, query: dict[str, Any]) -> dict[str, Any]:
    refresh(dataset_id); started = time.perf_counter()
    query = {"dataset_id": dataset_id, "dataset_version": dataset_version(dataset_id), **query}
    items = ExperimentRetriever(ExperimentMemoryRegistry(memory_root(dataset_id)).all()).similar(query, int(query.get("limit") or 5))
    return {"items": items, "count": len(items), "performance_ms": {"similarity_search": round((time.perf_counter()-started)*1000, 3)}}


def credits(dataset_id: str, kind: str) -> list[dict]:
    groups = refresh(dataset_id)["credits"]
    if kind not in groups: raise KeyError(kind)
    return groups[kind]


def train(dataset_id: str, user_confirmed: bool) -> dict:
    refresh(dataset_id); rows = ExperimentMemoryRegistry(memory_root(dataset_id)).all()
    started = time.perf_counter(); result = SurrogateTrainer(memory_root(dataset_id) / "surrogate").train(rows, user_confirmed=user_confirmed)
    result["performance_ms"] = {"surrogate_train": round((time.perf_counter()-started)*1000, 3)}
    return result


def models(dataset_id: str) -> list[dict]:
    return SurrogateRegistry(memory_root(dataset_id) / "surrogate").all()


def model(dataset_id: str, surrogate_id: str) -> dict:
    row = SurrogateRegistry(memory_root(dataset_id) / "surrogate").get(surrogate_id)
    if not row: raise KeyError(surrogate_id)
    return row


def predict(dataset_id: str, candidate: dict[str, Any]) -> dict:
    started = time.perf_counter(); result = SurrogateTrainer(memory_root(dataset_id) / "surrogate").predict({"dataset_id": dataset_id, "dataset_version": dataset_version(dataset_id), **candidate}, candidate.get("surrogate_id"))
    result["performance_ms"] = {"surrogate_predict": round((time.perf_counter()-started)*1000, 3)}
    return result


def rank_candidates(dataset_id: str, candidates: list[dict], opportunity_index: int = 0) -> dict:
    refresh(dataset_id); rows = ExperimentMemoryRegistry(memory_root(dataset_id)).all(); trainer = SurrogateTrainer(memory_root(dataset_id) / "surrogate")
    prepared = [{"dataset_id": dataset_id, "dataset_version": dataset_version(dataset_id), **x} for x in candidates]
    started = time.perf_counter(); ranked = CandidateRanker(rows, trainer).rank(prepared, opportunity_index=opportunity_index)
    return {"items": ranked, "ranking_mode": ranked[0]["ranking_mode"] if ranked else "PHASE5_FALLBACK", "policy": "70_30_DETERMINISTIC", "performance_ms": {"candidate_rank": round((time.perf_counter()-started)*1000, 3)}}


def diagnostics(dataset_id: str) -> dict:
    refresh(dataset_id);rows=ExperimentMemoryRegistry(memory_root(dataset_id)).all();usable=[x for x in rows if x.get("counterfactual_decision") in {"POSITIVE","NEUTRAL","NEGATIVE","UNSTABLE"}]
    if len(usable)<30:
        return {"status":"SURROGATE_INSUFFICIENT_DATA","count":len(usable),"audit":audit_dataset(usable) if usable else {},"model_comparison":{},"ablation":{}}
    return {"status":"READY","count":len(usable),"audit":audit_dataset(usable),"model_comparison":compare_models(usable),"ablation":feature_group_ablation(usable)}


def decision_context(dataset_id: str, query: dict | None = None) -> dict:
    refreshed = refresh(dataset_id); rows = ExperimentMemoryRegistry(memory_root(dataset_id)).all()
    query = {"dataset_id": dataset_id, "dataset_version": dataset_version(dataset_id), **(query or {})}
    retrieved = ExperimentRetriever(rows).context(query)
    return {"source": "EXPERIMENT_MEMORY", "summary": {"total": len(rows), "outcomes": {key: sum(x.get("counterfactual_decision") == key for x in rows) for key in ("POSITIVE", "NEUTRAL", "NEGATIVE", "UNSTABLE", "FAILED")}}, "working_memory": rows[-3:], "episodic_memory": retrieved["similar"], "aggregate_credit": {key: value[:5] for key, value in refreshed["credits"].items()}, **retrieved}
