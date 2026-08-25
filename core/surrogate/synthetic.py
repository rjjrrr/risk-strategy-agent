from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np


GROUND_TRUTH_VERSION = "synthetic-surrogate-v2.0"


def generate_synthetic_v2(count: int = 1500, seed: int = 20260824) -> list[dict]:
    """Generate learnable but noisy meta experiments; latent fields are test-only targets."""
    rng = np.random.default_rng(seed)
    feature_types = ["WINDOW_COUNT", "RATIO", "ENTITY_NUNIQUE", "COMPOSITE", "MISSING_FLAG", "RULE_GROUP_DERIVED"]
    domains = ["DEVICE", "IP", "LOCATION", "INCOME", "APPLICATION_BEHAVIOR", "CREDIT_HISTORY", "PROFILE", "RULE_DERIVED"]
    models = ["LR", "LGBM"]
    rows = []
    for i in range(count):
        feature_type = str(rng.choice(feature_types)); domain = str(rng.choice(domains)); model = str(rng.choice(models))
        psi = float(np.clip(rng.beta(1.3, 8) * .65, 0, .65)); correlation = float(rng.beta(2, 4))
        novelty = str(rng.choice(["HIGH", "MEDIUM", "LOW"], p=[.35, .45, .2]))
        hist_credit = float(np.clip(rng.beta(3, 3), .05, .95)); iv = float(np.clip(rng.lognormal(-3.0, .65), 0, .5))
        time_phase = i / max(1, count - 1)
        latent = -0.75 + 0.65 * (feature_type == "WINDOW_COUNT") + 1.0 * (feature_type == "WINDOW_COUNT" and model == "LGBM") + .9 * (feature_type == "RATIO" and model == "LR") + .5 * (domain in {"DEVICE", "CREDIT_HISTORY"}) + 1.5 * (hist_credit - .5) + .5 * (novelty == "HIGH") + 3.0 * iv - 4.0 * psi - 1.5 * max(0, correlation - .7) - .22 * (time_phase > .75)
        probability = float(1 / (1 + np.exp(-latent)))
        positive = bool(rng.random() < probability)
        unstable = bool(psi >= .25 and rng.random() < min(.9, .3 + psi))
        neutral = bool(not positive and not unstable and correlation >= .75 and rng.random() < .65)
        outcome = "UNSTABLE" if unstable else "POSITIVE" if positive else "NEUTRAL" if neutral else "NEGATIVE"
        expected_gain = -.004 + .026 * probability - .020 * psi - .008 * max(0, correlation - .7)
        gain = float(expected_gain + rng.normal(0, .0035)); gain = gain if outcome == "POSITIVE" else min(gain, .0015) if outcome == "NEUTRAL" else min(gain, 0)
        rows.append({
            "experiment_id": f"SYNV2_{i:05d}", "timestamp": (datetime(2024,1,1,tzinfo=timezone.utc)+timedelta(hours=i)).isoformat(),
            "dataset_id": "SYNTHETIC_V2", "dataset_version": GROUND_TRUTH_VERSION, "data_source": "SYNTHETIC", "segment": "NEW",
            "model_type": model, "action_type": "TEST_FEATURE", "hypothesis_id": f"H_{i%41}", "feature_ids": [f"F_{i}"],
            "feature_types": [feature_type], "semantic_domains": [domain], "evidence_types": [str(rng.choice(["TEMPORAL_PATTERN","SEMANTIC_RELATION","RULE_SIGNAL","MODEL_RESIDUAL"]))],
            "baseline_state_id": "S0", "baseline_metrics": {"oot_auc": .62 + float(rng.normal(0,.025)), "oot_ks": .25 + float(rng.normal(0,.02)), "lift_10": 1.8 + float(rng.normal(0,.15)), "auc_gap": abs(float(rng.normal(.04,.015)))},
            "result_metrics": {}, "delta_metrics": {"delta_oot_auc": gain, "delta_oot_ks": gain*2+float(rng.normal(0,.004)), "delta_lift10": gain*9+float(rng.normal(0,.02))},
            "counterfactual_decision": outcome, "action_outcome": outcome, "feature_credit": {}, "hypothesis_credit": {}, "diagnosis_before": str(rng.choice(["LOW_SIGNAL","MODEL_MISMATCH","FEATURE_DRIFT","REDUNDANCY"])),
            "state_after": f"S{i}", "cost": float(rng.choice([1,2,3],p=[.55,.35,.1])), "runtime": float(rng.lognormal(-1,.4)), "human_approval": False, "success": outcome == "POSITIVE",
            "validation_metrics": {"decision": "PROMISING" if iv>.04 else "EXPLORATORY", "iv": iv, "psi": psi, "valid_rate": float(rng.uniform(.9,1)), "feature_novelty": novelty, "max_existing_correlation": correlation, "lr_eligible": True, "lgbm_eligible": True},
            "feature_count_before": int(rng.integers(8,35)), "feature_credit_before": hist_credit, "hypothesis_credit_before": float(np.clip(hist_credit+rng.normal(0,.12),0,1)), "hypothesis_confidence": str(rng.choice(["HIGH","MEDIUM","LOW"],p=[.45,.45,.1])),
            "source": "SYNTHETIC", "experiment_signature": f"SYNV2_SIG_{i}",
            "ground_truth_function_version": GROUND_TRUTH_VERSION, "latent_expected_gain": expected_gain, "latent_positive_probability": probability,
        })
    return rows
