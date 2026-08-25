from __future__ import annotations

from pathlib import Path

from core.model_agent.registry import JsonRegistry


class SurrogateRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "surrogate_models.json", "surrogate_id")


class SurrogatePredictionRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "surrogate_predictions.json", "prediction_id")
