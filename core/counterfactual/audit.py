from __future__ import annotations

from pathlib import Path

from core.model_agent.registry import JsonRegistry


class CounterfactualRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "counterfactual_experiments.json", "experiment_id")

    def duplicate(self, signature: str) -> dict | None:
        return next((row for row in self.all() if row.get("experiment_signature") == signature and row.get("decision") != "FAILED"), None)


class FeatureCreditRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "feature_credit_registry.json", "credit_id")


class FeatureMarginalGainRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "feature_marginal_gain_registry.json", "gain_id")


class HypothesisCreditRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "hypothesis_credit_registry.json", "credit_id")


class RemoveFeatureProposalRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "remove_feature_proposals.json", "proposal_id")
