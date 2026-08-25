from __future__ import annotations

from typing import Any

from .audit import ExperimentMemoryRegistry
from .schemas import ExperimentMemoryRecord
from .serialization import assert_no_raw_data, stable_hash


OUTCOME_MAP = {
    "ACCEPT_PERFORMANCE": "POSITIVE", "ACCEPT_SIMPLIFICATION": "POSITIVE",
    "POSITIVE": "POSITIVE", "NEUTRAL": "NEUTRAL", "NEGATIVE": "NEGATIVE",
    "UNSTABLE": "UNSTABLE", "FAILED": "FAILED", "RUNNING": "RUNNING",
}


class ExperimentMemoryBuilder:
    def __init__(self, registry: ExperimentMemoryRegistry):
        self.registry = registry

    def build(self, experiments: list[dict[str, Any]], *, dataset_id: str, dataset_version: str = "UNKNOWN",
              features: list[dict] | None = None, hypotheses: list[dict] | None = None,
              validations: list[dict] | None = None, feature_credits: list[dict] | None = None,
              hypothesis_credits: list[dict] | None = None, source: str = "REAL") -> dict[str, Any]:
        feature_map = {str(x.get("feature_id")): x for x in features or []}
        hypothesis_map = {str(x.get("hypothesis_id")): x for x in hypotheses or []}
        validation_map = {str(x.get("feature_id")): x for x in validations or []}
        feature_credit_map = {(str(x.get("feature_id")), str(x.get("model_type"))): x for x in feature_credits or []}
        hypothesis_credit_map = {str(x.get("hypothesis_id") or x.get("credit_id")): x for x in hypothesis_credits or []}
        inserted = duplicates = 0
        for experiment in experiments:
            record = self.from_experiment(
                experiment, dataset_id=dataset_id, dataset_version=dataset_version,
                feature_map=feature_map, hypothesis_map=hypothesis_map, validation_map=validation_map,
                feature_credit_map=feature_credit_map, hypothesis_credit_map=hypothesis_credit_map, source=source,
            )
            _, created = self.registry.add_deduplicated(record.model_dump())
            inserted += int(created); duplicates += int(not created)
        return {"total": len(self.registry.all()), "inserted": inserted, "duplicates": duplicates}

    @staticmethod
    def from_experiment(experiment: dict[str, Any], *, dataset_id: str, dataset_version: str,
                        feature_map: dict[str, dict], hypothesis_map: dict[str, dict],
                        validation_map: dict[str, dict], feature_credit_map: dict[tuple[str, str], dict],
                        hypothesis_credit_map: dict[str, dict], source: str = "REAL") -> ExperimentMemoryRecord:
        feature_ids = [str(x) for x in (experiment.get("changed_features") or experiment.get("added_features") or experiment.get("feature_ids") or [])]
        direct_id = experiment.get("feature_id")
        if direct_id and str(direct_id) not in feature_ids:
            feature_ids = [str(direct_id)] + feature_ids
        # changed_features may contain names; only enrich IDs that exist in the registry.
        enriched = [feature_map[x] for x in feature_ids if x in feature_map]
        if direct_id and str(direct_id) in feature_map and feature_map[str(direct_id)] not in enriched:
            enriched.insert(0, feature_map[str(direct_id)])
        hypothesis_id = experiment.get("hypothesis_id") or next((x.get("hypothesis_id") for x in enriched if x.get("hypothesis_id")), None)
        hypothesis = hypothesis_map.get(str(hypothesis_id), {})
        model_type = str(experiment.get("model_type") or "UNKNOWN").upper()
        feature_types = sorted({str(x.get("feature_type") or "UNKNOWN") for x in enriched}) or [str(experiment.get("feature_type") or "UNKNOWN")]
        domains = sorted({str(x.get("semantic_domain") or "UNKNOWN") for x in enriched}) or [str(experiment.get("semantic_domain") or "UNKNOWN")]
        evidence = hypothesis.get("evidence_types") or ([hypothesis.get("evidence_type")] if hypothesis.get("evidence_type") else experiment.get("evidence_types") or [])
        decision = str(experiment.get("decision") or experiment.get("counterfactual_decision") or "REVIEW")
        outcome = OUTCOME_MAP.get(decision, "REVIEW")
        first_feature = str(direct_id or (feature_ids[0] if feature_ids else ""))
        validation = validation_map.get(first_feature, experiment.get("validation_metrics") or {})
        validation_metrics = validation.get("metrics", validation) if isinstance(validation, dict) else {}
        signature = experiment.get("experiment_signature") or stable_hash({
            "feature_version": experiment.get("feature_version"), "features": feature_ids,
            "model": model_type, "params": experiment.get("model_params_hash") or experiment.get("model_params_after") or experiment.get("model_params"),
            "split": experiment.get("split_hash") or experiment.get("split_id"), "seed": experiment.get("seed", 42),
            "type": experiment.get("experiment_type") or experiment.get("action_type"),
        })
        record = ExperimentMemoryRecord(
            experiment_id=str(experiment.get("experiment_id")), timestamp=str(experiment.get("finished_at") or experiment.get("created_at")),
            dataset_id=dataset_id, dataset_version=dataset_version, data_source=str(experiment.get("data_source") or "CURRENT_WIDE_TABLE"),
            segment=str(experiment.get("segment") or "NEW"), model_type=model_type,
            action_type=str(experiment.get("action_type") or ("REMOVE_FEATURE_ABLATION" if experiment.get("experiment_type") in {"FEATURE_REMOVE", "FEATURE_GROUP_REMOVE"} else "TEST_FEATURE")),
            hypothesis_id=hypothesis_id, feature_ids=feature_ids, feature_types=feature_types,
            semantic_domains=domains, evidence_types=[str(x) for x in evidence if x],
            baseline_state_id=experiment.get("baseline_state_id") or experiment.get("parent_state_id"),
            baseline_metrics=experiment.get("metrics_before") or {}, result_metrics=experiment.get("metrics_after") or {},
            delta_metrics=experiment.get("delta_metrics") or {}, counterfactual_decision=outcome,
            action_outcome=str(experiment.get("action_outcome") or decision),
            feature_credit=feature_credit_map.get((first_feature, model_type), {}),
            hypothesis_credit=hypothesis_credit_map.get(str(hypothesis_id), {}),
            diagnosis_before=str(experiment.get("diagnosis_before") or "UNKNOWN"), state_after=experiment.get("challenger_state_id") or experiment.get("created_state_id"),
            cost=float(experiment.get("cost") or 0), runtime=float(experiment.get("runtime") or experiment.get("runtime_seconds") or 0),
            human_approval=bool(experiment.get("human_approval", False)), success=outcome == "POSITIVE",
            validation_metrics=validation_metrics, feature_count_before=len(experiment.get("baseline_features") or []),
            source=source, memory_source=source, experiment_signature=str(signature),
        )
        assert_no_raw_data(record.model_dump())
        return record
