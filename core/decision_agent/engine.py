from __future__ import annotations

import uuid
from typing import Any

from .schemas import CandidateAction, DecisionEvidence, DecisionOutput, ExperimentPlan


CONFIDENCE = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
COST = {"LOW": 2, "MEDIUM": 1, "HIGH": 0}
RISK = {"LOW": 2, "MEDIUM": 1, "HIGH": 0}
NOVELTY = {"HIGH": 2, "MEDIUM": 1, "LOW": 0, "UNKNOWN": 0}
CREDIT = {"POSITIVE": 2, "NEUTRAL": 0, "NEGATIVE": -2, "UNSTABLE": -3, "UNKNOWN": 0}

HUMAN_REQUIRED_ACTIONS = {
    "MODEL_TUNE", "DATA_CLEAN_PROPOSAL", "FEATURE_TRANSFORM_PROPOSAL",
}
AUTO_ALLOWED_ACTIONS = {
    "TEST_FEATURE", "TEST_HYPOTHESIS", "REMOVE_FEATURE_ABLATION", "MODEL_SWITCH",
    "ROLLBACK", "STOP_EXPLORATION", "NO_ACTION",
}
ACTION_TOOL = {
    "TEST_FEATURE": "run_lr_counterfactual",
    "TEST_HYPOTHESIS": "run_lr_counterfactual",
    "REMOVE_FEATURE_ABLATION": "run_feature_ablation",
    "MODEL_SWITCH": "evaluate_model",
    "MODEL_TUNE": "evaluate_model",
    "DATA_CLEAN_PROPOSAL": "request_analysis_agent",
    "FEATURE_TRANSFORM_PROPOSAL": "request_analysis_agent",
    "REQUEST_ANALYSIS": "request_analysis_agent",
    "ROLLBACK": "rollback_state",
}


def _metrics(context: dict[str, Any]) -> dict[str, Any]:
    state = context.get("current_state") or context.get("model_state") or {}
    return state.get("metrics") or state.get("model_state", {}).get("metrics") or context.get("model_state", {}).get("metrics") or {}


def _latest_experiments(context: dict[str, Any]) -> list[dict[str, Any]]:
    history = context.get("experiment_history") or {}
    return history.get("latest", []) if isinstance(history, dict) else list(history)[-6:]


def _feature_id(row: dict[str, Any]) -> str | None:
    return row.get("feature_id") or row.get("feature", {}).get("feature_id")


class DecisionEngine:
    """Deterministic diagnosis/ranking layer. It never executes experiments or mutates model state."""

    def diagnose(self, context: dict[str, Any], *, blocked_features=None, tested_actions=None) -> DecisionOutput:
        blocked = set(blocked_features or [])
        tested = list(tested_actions or [])
        metrics = _metrics(context)
        validations = list(context.get("feature_validation") or [])
        counterfactual = list(context.get("counterfactual_history") or [])
        experiments = _latest_experiments(context)
        leakage = list(context.get("confirmed_leakage") or [])
        leakage.extend(str(_feature_id(row)) for row in validations if row.get("decision") == "LEAKAGE_RISK" and _feature_id(row))

        diagnosis = "NO_ACTION_REQUIRED"
        confidence = "MEDIUM"
        evidence: list[DecisionEvidence] = []
        related_features: list[str] = []

        if leakage:
            diagnosis, confidence, related_features = "LEAKAGE", "HIGH", sorted(set(leakage))
            evidence.append(DecisionEvidence(source_id="GOVERNANCE", reason_code="CONFIRMED_LEAKAGE", facts={"feature_ids": related_features}))
        elif context.get("data_health", {}).get("severe_issue"):
            diagnosis, confidence = "DATA_QUALITY", "HIGH"
            evidence.append(DecisionEvidence(source_id="DATA_HEALTH", reason_code="SEVERE_DATA_QUALITY", facts=context["data_health"]))
        elif int(context.get("data_health", {}).get("sample_size") or 10**9) < int(context.get("data_health", {}).get("minimum_sample") or 500):
            diagnosis, confidence = "INSUFFICIENT_SAMPLE", "HIGH"
            evidence.append(DecisionEvidence(source_id="DATA_HEALTH", reason_code="SAMPLE_BELOW_MINIMUM", facts={key: context["data_health"].get(key) for key in ("sample_size", "minimum_sample")}))
        elif float(metrics.get("train_oot_auc_gap") or metrics.get("auc_gap") or 0) > 0.1 or float(metrics.get("dev_auc") or 0) - float(metrics.get("oot_auc") or 0) > 0.1:
            diagnosis, confidence = "OVERFITTING", "HIGH"
            evidence.append(DecisionEvidence(source_id="CURRENT_STATE", reason_code="DEV_OOT_GAP", facts={key: metrics.get(key) for key in ("dev_auc", "oot_auc", "train_oot_auc_gap", "auc_gap") if key in metrics}))
        elif drift := [row for row in validations if float(row.get("metrics", {}).get("psi") or row.get("psi") or 0) >= 0.25]:
            diagnosis, confidence = "FEATURE_DRIFT", "HIGH"
            related_features = [str(_feature_id(row)) for row in drift if _feature_id(row)]
            evidence.append(DecisionEvidence(source_id="FEATURE_VALIDATION", reason_code="PSI_THRESHOLD", facts={"features": related_features, "psi": {str(_feature_id(row)): row.get("metrics", {}).get("psi", row.get("psi")) for row in drift}}))
        elif redundant := [row for row in validations if row.get("metrics", {}).get("feature_novelty") == "LOW" or float(row.get("metrics", {}).get("max_existing_correlation") or row.get("max_existing_correlation") or 0) >= 0.95]:
            neutral_ids = {_feature_id(row) for row in counterfactual + experiments if row.get("decision") == "NEUTRAL"}
            matched = [row for row in redundant if _feature_id(row) in neutral_ids]
            if matched:
                diagnosis, confidence = "REDUNDANCY", "HIGH"
                related_features = [str(_feature_id(row)) for row in matched]
                evidence.append(DecisionEvidence(source_id="FEATURE_VALIDATION", reason_code="HIGH_CORRELATION_NEUTRAL_GAIN", facts={"feature_ids": related_features}))
        if diagnosis == "NO_ACTION_REQUIRED" and self._model_mismatch(counterfactual + experiments):
            feature, lr_decision, lgbm_decision = self._model_mismatch(counterfactual + experiments)
            diagnosis, confidence, related_features = "MODEL_MISMATCH", "HIGH", [feature]
            evidence.append(DecisionEvidence(source_id="COUNTERFACTUAL_HISTORY", reason_code="LR_NEUTRAL_LGBM_POSITIVE", facts={"feature_id": feature, "LR": lr_decision, "LGBM": lgbm_decision}))
        if diagnosis == "NO_ACTION_REQUIRED" and any(row.get("decision") == "UNSTABLE" for row in counterfactual + experiments):
            row = next(row for row in reversed(counterfactual + experiments) if row.get("decision") == "UNSTABLE")
            diagnosis, confidence = "UNSTABLE_GAIN", "HIGH"
            related_features = [str(_feature_id(row))] if _feature_id(row) else []
            evidence.append(DecisionEvidence(source_id="COUNTERFACTUAL_HISTORY", reason_code="UNSTABLE_EXPERIMENT", facts={"experiment_id": row.get("experiment_id"), "feature_id": _feature_id(row)}))
        if diagnosis == "NO_ACTION_REQUIRED" and context.get("segment_mixture"):
            diagnosis, confidence = "SEGMENT_MIXTURE", "HIGH"
            evidence.append(DecisionEvidence(source_id="RULE_SUMMARY", reason_code="SUBGROUP_DIRECTION_CONFLICT", facts={"segment_mixture": True}))

        no_gain = [row for row in experiments if row.get("decision") in {"NEUTRAL", "NEGATIVE", "REJECT"}]
        if diagnosis == "NO_ACTION_REQUIRED" and (len(no_gain[-2:]) >= 2 or context.get("model_state", {}).get("low_signal")):
            diagnosis, confidence = "LOW_SIGNAL", "HIGH"
            evidence.append(DecisionEvidence(source_id="EXPERIMENT_HISTORY", reason_code="CONSECUTIVE_NO_GAIN", facts={"recent_decisions": [row.get("decision") for row in no_gain[-2:]]}))
        elif diagnosis == "NO_ACTION_REQUIRED" and metrics and float(metrics.get("oot_auc") or 1) < 0.58:
            diagnosis, confidence = "LOW_SIGNAL", "MEDIUM"
            evidence.append(DecisionEvidence(source_id="CURRENT_STATE", reason_code="LOW_OOT_SIGNAL", facts={"oot_auc": metrics.get("oot_auc")}))

        candidates = self._candidates(diagnosis, context, related_features, blocked, tested, len(no_gain[-2:]) >= 2)
        ranked = sorted((self._rank(row) for row in candidates), key=lambda row: (-row.priority, row.action_type, row.feature_ids))
        # Deterministic 70/30 policy over explicit decision opportunities: seven
        # evidence/credit-first slots, then three novelty-first exploration slots.
        exploration_slot = len(tested) % 10 >= 7
        exploratory = [row for row in ranked if row.action_type == "TEST_FEATURE" and row.novelty == "HIGH"]
        selected = exploratory[0] if exploration_slot and exploratory else ranked[0] if ranked else None
        stop_reason = None
        if selected and selected.action_type in {"STOP_EXPLORATION", "NO_ACTION"}:
            stop_reason = selected.reason
        if not selected:
            selected = CandidateAction(action_type="NO_ACTION", reason="No safe and useful action is available")
            ranked = [selected]
            stop_reason = "NO_AVAILABLE_ACTION"
        return DecisionOutput(
            diagnosis=diagnosis, diagnosis_confidence=confidence, evidence=evidence,
            candidate_actions=ranked, selected_action=selected,
            expected_effect=self._expected_effect(selected.action_type), risk_level=selected.risk,
            requires_human_approval=selected.requires_human_approval,
            stop_reason=stop_reason, missing_information=self._missing(context, selected),
        )

    @staticmethod
    def _model_mismatch(rows: list[dict[str, Any]]):
        grouped: dict[str, dict[str, str]] = {}
        for row in rows:
            feature = _feature_id(row)
            model = row.get("model_type")
            if feature and model in {"LR", "LGBM"}:
                grouped.setdefault(str(feature), {})[str(model)] = str(row.get("decision"))
        for feature, decisions in grouped.items():
            if decisions.get("LR") == "NEUTRAL" and decisions.get("LGBM") == "POSITIVE":
                return feature, "NEUTRAL", "POSITIVE"
        return None

    def _candidates(self, diagnosis, context, related, blocked, tested, two_no_gain):
        rows: list[CandidateAction] = []
        tested_features = {feature for action in tested for feature in action.get("feature_ids", [])}
        features = [row for row in context.get("candidate_features", []) if str(_feature_id(row)) not in blocked | tested_features]
        credit_map = {str(row.get("feature_id")): row for row in context.get("feature_credit", [])}
        hypothesis_map = {str(row.get("hypothesis_id")): row for row in context.get("hypothesis_credit", [])}
        promising = [row for row in features if row.get("validation_result", {}).get("decision") in {"PROMISING", "EXPLORATORY"} or row.get("decision") in {"PROMISING", "EXPLORATORY"}]
        if diagnosis == "LEAKAGE":
            return [CandidateAction(action_type="STOP_EXPLORATION", reason="Confirmed leakage is isolated from the experimental pool", feature_ids=related, risk="HIGH", evidence_confidence="HIGH")]
        if diagnosis == "DATA_QUALITY":
            return [CandidateAction(action_type="DATA_CLEAN_PROPOSAL", reason="Severe data quality issue requires reviewed remediation", risk="HIGH", cost="MEDIUM", evidence_confidence="HIGH", requires_human_approval=True)]
        if diagnosis == "INSUFFICIENT_SAMPLE":
            return [CandidateAction(action_type="REQUEST_MORE_DATA", reason="Sample is below the deterministic minimum", risk="LOW", evidence_confidence="HIGH", requires_human_approval=True), CandidateAction(action_type="STOP_EXPLORATION", reason="Do not train on insufficient sample", risk="LOW")]
        if diagnosis in {"OVERFITTING", "UNSTABLE_GAIN"}:
            if context.get("last_stable_state"):
                rows.append(CandidateAction(action_type="ROLLBACK", reason="Return to the last stable state", risk="LOW", evidence_confidence="HIGH"))
            if related:
                rows.append(CandidateAction(action_type="REMOVE_FEATURE_ABLATION", reason="Test one suspect feature removal", feature_ids=[related[0]], model_type=context.get("model_state", {}).get("model_type") or "LR", risk="MEDIUM", cost="LOW", evidence_confidence="HIGH"))
            return rows
        if diagnosis in {"FEATURE_DRIFT", "REDUNDANCY"}:
            if related:
                rows.append(CandidateAction(action_type="REMOVE_FEATURE_ABLATION", reason="Measure one feature's removable marginal contribution", feature_ids=[related[0]], model_type=context.get("model_state", {}).get("model_type") or "LR", risk="MEDIUM", cost="LOW", evidence_confidence="HIGH"))
            rows.append(CandidateAction(action_type="REQUEST_ANALYSIS", reason="Request a stable alternative or subgroup evidence", risk="LOW", cost="LOW", evidence_confidence="MEDIUM", requires_human_approval=True))
            return rows
        if diagnosis == "MODEL_MISMATCH":
            current = context.get("model_state", {}).get("model_type") or "LR"
            return [CandidateAction(action_type="MODEL_SWITCH", reason="The same feature has model-specific nonlinear gain", model_type="LGBM" if current == "LR" else "LR", risk="MEDIUM", cost="MEDIUM", evidence_confidence="HIGH")]
        if diagnosis == "SEGMENT_MIXTURE":
            return [CandidateAction(action_type="REQUEST_ANALYSIS", reason="Request subgroup analysis; do not train a production submodel", risk="MEDIUM", cost="LOW", evidence_confidence="HIGH", requires_human_approval=True)]
        if diagnosis == "LOW_SIGNAL":
            if two_no_gain:
                return [CandidateAction(action_type="STOP_EXPLORATION", reason="Two consecutive experiments produced no material gain", risk="LOW", evidence_confidence="HIGH")]
            return [CandidateAction(action_type="REQUEST_ANALYSIS", reason="Return to high-confidence hypothesis generation", risk="LOW", cost="LOW", evidence_confidence="HIGH", requires_human_approval=True), CandidateAction(action_type="MODEL_SWITCH", reason="Test model mismatch without generating random features", model_type="LGBM", risk="MEDIUM", cost="MEDIUM")]
        for feature in promising:
            fid = str(_feature_id(feature))
            validation = feature.get("validation_result") or feature
            model = "LR" if validation.get("lr_eligible", True) else "LGBM"
            credit = credit_map.get(fid, {})
            hypothesis = hypothesis_map.get(str(feature.get("hypothesis_id")), {})
            evidence_confidence = "HIGH" if hypothesis.get("support_status") == "SUPPORTED" else feature.get("confidence", "HIGH")
            memory = feature.get("experiment_ranking") or {}
            prediction = memory.get("surrogate_prediction") or {}
            rows.append(CandidateAction(candidate_id=memory.get("candidate_id") or fid, action_type="TEST_FEATURE", reason="Untested validated feature ranked by evidence, credit, novelty, cost and risk", feature_ids=[fid], hypothesis_id=feature.get("hypothesis_id"), feature_type=feature.get("feature_type", "UNKNOWN"), semantic_domain=feature.get("semantic_domain", "UNKNOWN"), model_type=model, risk="LOW", cost=feature.get("estimated_cost", "LOW"), evidence_confidence=evidence_confidence, novelty=validation.get("metrics", {}).get("feature_novelty", "UNKNOWN"), credit_direction=credit.get("overall_direction", feature.get("credit_direction", "UNKNOWN")), historical_credit=memory.get("historical_credit") or {}, similar_experiments=prediction.get("similar_experiments") or [], surrogate_prediction=prediction, expected_delta_auc=memory.get("expected_delta_auc"), expected_delta_ks=memory.get("expected_delta_ks"), expected_delta_lift10=memory.get("expected_delta_lift10"), positive_probability=memory.get("positive_probability"), uncertainty=memory.get("uncertainty", "HIGH"), ranking_mode=memory.get("ranking_mode", "PHASE5_FALLBACK"), expected_utility=float(memory.get("priority") or 0)))
        if not rows:
            rows.append(CandidateAction(action_type="NO_ACTION", reason="Stable state has no untested validated candidate", risk="LOW"))
        return rows

    @staticmethod
    def _rank(action: CandidateAction) -> CandidateAction:
        # Phase 7A final ranking is deterministic Phase 5 only; expected_utility is shadow telemetry.
        action.priority = float(CONFIDENCE[action.evidence_confidence] + COST[action.cost] + RISK[action.risk] + NOVELTY[action.novelty] + CREDIT[action.credit_direction])
        return action

    @staticmethod
    def _expected_effect(action: str) -> str:
        return {
            "TEST_FEATURE": "Measure one feature's OOT marginal contribution under fixed split, parameters, seed and preprocessing.",
            "TEST_HYPOTHESIS": "Test one hypothesis through one controlled feature experiment.",
            "REMOVE_FEATURE_ABLATION": "Measure whether one feature can be removed without material performance loss.",
            "MODEL_SWITCH": "Compare model-family suitability without changing the feature set.",
            "ROLLBACK": "Restore the recorded last stable model state.",
            "REQUEST_ANALYSIS": "Request evidence without executing a model experiment.",
            "REQUEST_MORE_DATA": "Pause training until the required sample is available.",
            "STOP_EXPLORATION": "Stop additional experiments and preserve the current stable state.",
            "NO_ACTION": "Preserve the current state.",
        }.get(action, "Produce a reviewed proposal without automatic production mutation.")

    @staticmethod
    def _missing(context, selected):
        missing = []
        if selected.action_type not in {"NO_ACTION", "STOP_EXPLORATION", "REQUEST_MORE_DATA"} and not context.get("current_state") and not context.get("model_state"):
            missing.append("CURRENT_STATE")
        if selected.action_type in {"TEST_FEATURE", "REMOVE_FEATURE_ABLATION"} and not selected.feature_ids:
            missing.append("FEATURE_ID")
        return missing

    def compile_plan(self, decision_id: str, decision: DecisionOutput, *, baseline_state_id: str | None) -> ExperimentPlan:
        action = decision.selected_action
        if action is None:
            raise ValueError("Decision has no selected action")
        tool = ACTION_TOOL.get(action.action_type)
        return ExperimentPlan(
            plan_id=f"DP_{uuid.uuid4().hex[:12]}", decision_id=decision_id,
            action_type=action.action_type, hypothesis_id=action.hypothesis_id,
            feature_ids=action.feature_ids, model_type=action.model_type,
            baseline_state_id=baseline_state_id, expected_change=decision.expected_effect,
            expected_metric_direction={"oot_auc": "UP", "oot_ks": "UP", "lift_10": "UP", "auc_gap": "STABLE", "score_psi": "STABLE"} if action.action_type in {"TEST_FEATURE", "TEST_HYPOTHESIS", "MODEL_SWITCH"} else {"feature_count": "DOWN", "oot_auc": "STABLE"} if action.action_type == "REMOVE_FEATURE_ABLATION" else {},
            required_tools=[tool] if tool else [], risk=action.risk, cost=action.cost,
            human_approval_required=action.requires_human_approval or action.action_type in HUMAN_REQUIRED_ACTIONS,
        )
