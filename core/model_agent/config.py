"""Central configuration for Model Agent V1 gates and budgets."""

MAX_AGENT_ROUNDS = 3
MAX_HYPOTHESES_PER_ROUND = 20
MAX_VALIDATED_FEATURES = 10
MAX_LR_NEW_FEATURES = 5
MAX_LGBM_NEW_FEATURES = 10
RANDOM_STATE = 42

HARD_GATES = {
    "min_oot_auc": 0.62,
    "min_oot_ks": 0.20,
    "max_auc_gap": 0.08,
    "max_core_feature_psi": 0.25,
}

MATERIAL_IMPROVEMENT = {
    "oot_auc": 0.005,
    "oot_ks": 0.01,
    "lift_at_10": 0.05,
}

FEATURE_TYPES = {
    "COUNT", "FREQUENCY", "RATIO", "DIFFERENCE", "TIME_WINDOW",
    "SHORT_LONG_RATIO", "SHARING_ASSOCIATION", "RULE_GROUP_FEATURE", "RAW",
}

MODEL_STAGES = (
    "semantic_analysis", "hypothesis", "feature_engineering", "cheap_validation",
    "model_baseline", "experiments", "evaluation", "diagnosis", "final_review",
)

STAGE_STATUSES = {"NOT_STARTED", "RUNNING", "SUCCESS", "FAILED", "STALE", "WAITING_APPROVAL"}
