from __future__ import annotations

from pathlib import Path

from core.model_agent.registry import JsonRegistry


class ExperimentMemoryRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "experiment_memory.json", "experiment_id")

    def add_deduplicated(self, row: dict) -> tuple[dict, bool]:
        duplicate = next((item for item in self.all() if item.get("experiment_signature") == row.get("experiment_signature")), None)
        if duplicate:
            return duplicate, False
        return self.add(row), True


class AggregateCreditRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "aggregate_credit.json", "credit_id")

    def replace(self, rows: list[dict]) -> None:
        self._write(rows)
