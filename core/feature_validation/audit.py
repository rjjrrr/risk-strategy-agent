from __future__ import annotations

from pathlib import Path

from core.model_agent.registry import JsonRegistry


class FeatureValidationRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "feature_validation_registry.json", "validation_id")

    def latest_for_feature(self, feature_id: str) -> dict | None:
        rows = [row for row in self.all() if row.get("feature_id") == feature_id]
        return rows[-1] if rows else None
