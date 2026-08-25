from __future__ import annotations

import uuid

from core.experiment_memory.aggregator import CreditAggregator
from core.experiment_memory.retriever import ExperimentRetriever
from .schemas import ExperimentCandidate


COST = {"LOW": 1.0, "MEDIUM": .5, "HIGH": 0.0}
NOVELTY = {"HIGH": 1.0, "MEDIUM": .5, "LOW": 0.0, "UNKNOWN": .25}


class CandidateRanker:
    def __init__(self, memory_rows: list[dict], trainer=None):
        self.rows = memory_rows; self.trainer = trainer
        self.credits = CreditAggregator().all_dimensions(memory_rows)

    def rank(self, candidates: list[dict], *, opportunity_index: int = 0) -> list[dict]:
        ranked = []
        for raw in candidates:
            candidate = ExperimentCandidate.model_validate({"candidate_id": raw.get("candidate_id") or f"EC_{uuid.uuid4().hex[:10]}", **raw})
            feature_credit = self._credit("model_specific", candidate.feature_type, candidate.model_type, candidate.dataset_id)
            domain_credit = self._credit("semantic_domains", candidate.semantic_domain, None, candidate.dataset_id)
            candidate.historical_credit = {"feature_type": feature_credit, "semantic_domain": domain_credit}
            prediction = self.trainer.predict(raw) if self.trainer else {"status": "SURROGATE_INSUFFICIENT_DATA", "fallback": True, "uncertainty": "HIGH"}
            candidate.surrogate_prediction = prediction
            candidate.uncertainty = prediction.get("uncertainty", "HIGH")
            if not prediction.get("fallback") and prediction.get("status") == "ACTIVE":
                candidate.expected_delta_auc = prediction.get("expected_delta_auc", 0.0)
                candidate.expected_delta_ks = prediction.get("expected_delta_ks", 0.0)
                candidate.expected_delta_lift10 = prediction.get("expected_delta_lift10", 0.0)
                candidate.positive_probability = prediction.get("positive_probability", 0.0)
                historical = float(feature_credit.get("smoothed_positive_rate", .5))
                candidate.priority = round(5 * candidate.positive_probability + 2 * historical + NOVELTY.get(candidate.novelty, .25) + COST.get(candidate.cost, .5) - float((candidate.validation_metrics or {}).get("psi") or 0), 6)
                candidate.ranking_mode = "SURROGATE"
            else:
                candidate.expected_delta_auc = prediction.get("expected_delta_auc", 0.0)
                candidate.expected_delta_ks = prediction.get("expected_delta_ks", 0.0)
                candidate.expected_delta_lift10 = prediction.get("expected_delta_lift10", 0.0)
                candidate.positive_probability = prediction.get("positive_probability", 0.0)
                historical = float(feature_credit.get("smoothed_positive_rate", .5))
                candidate.priority = round(2 * historical + NOVELTY.get(candidate.novelty, .25) + COST.get(candidate.cost, .5), 6)
                candidate.ranking_mode = "PHASE5_FALLBACK"
            similar = ExperimentRetriever(self.rows).similar(raw, 5)
            candidate.surrogate_prediction["similar_experiments"] = [{"experiment_id": x.get("experiment_id"), "outcome": x.get("counterfactual_decision"), "scope": x.get("scope")} for x in similar]
            candidate.ranking_reason = f"{candidate.ranking_mode}: predicted/credit + novelty - risk/cost; prediction never replaces actual counterfactual"
            ranked.append(candidate)
        # Deterministic 70/30: slots 7-9 select novelty-first, with unseen domains retained.
        exploration = opportunity_index % 10 >= 7
        return [x.model_dump() for x in sorted(ranked, key=(lambda x: (-NOVELTY.get(x.novelty, .25), -x.priority, x.candidate_id)) if exploration else (lambda x: (-x.priority, -NOVELTY.get(x.novelty, .25), x.candidate_id)))]

    def _credit(self, group: str, value: str, model: str | None, dataset_id: str) -> dict:
        dimension = "FEATURE_TYPE" if group == "model_specific" else "SEMANTIC_DOMAIN"
        scoped = CreditAggregator().aggregate(self.rows, dimension, by_model=bool(model), dataset_id=dataset_id)
        global_rows = self.credits.get(group, [])
        match = lambda x: x.get("value") == value and (not model or x.get("model_type") == model)
        same = [x for x in scoped if match(x)]
        cross = [x for x in global_rows if match(x)]
        return same[0] if same else cross[0] if cross else {"sample_count": 0, "smoothed_positive_rate": .5, "confidence": "LOW"}
