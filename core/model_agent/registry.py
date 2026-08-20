from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.json_utils import sanitize_json


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JsonRegistry:
    def __init__(self, path: str | Path, key: str):
        self.path = Path(path)
        self.key = key
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write([])

    def _read(self) -> list[dict[str, Any]]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, rows: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(sanitize_json(rows), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    def all(self) -> list[dict[str, Any]]:
        return self._read()

    def get(self, item_id: str) -> dict[str, Any] | None:
        return next((row for row in self._read() if row.get(self.key) == item_id), None)

    def add(self, row: dict[str, Any]) -> dict[str, Any]:
        rows = self._read()
        if any(item.get(self.key) == row.get(self.key) for item in rows):
            raise ValueError(f"Duplicate {self.key}: {row.get(self.key)}")
        row = {**row, "created_at": row.get("created_at", utc_now())}
        rows.append(row)
        self._write(rows)
        return row

    def update(self, item_id: str, **changes: Any) -> dict[str, Any]:
        rows = self._read()
        for row in rows:
            if row.get(self.key) == item_id:
                row.update(changes)
                row["updated_at"] = utc_now()
                self._write(rows)
                return row
        raise KeyError(item_id)

    def find(self, predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
        return [row for row in self._read() if predicate(row)]


class HypothesisRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "hypothesis_registry.json", "hypothesis_id")


class FeatureRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "feature_registry.json", "feature_id")

    def by_formula(self, formula: str, source_fields: list[str]) -> dict[str, Any] | None:
        signature = (formula.strip(), tuple(sorted(source_fields)))
        return next(
            (row for row in self.all() if (str(row.get("formula", "")).strip(), tuple(sorted(row.get("source_fields", [])))) == signature),
            None,
        )


class ExperimentRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "experiment_registry.json", "experiment_id")

    def duplicate(self, experiment_type: str, changes: dict[str, Any], model_type: str) -> dict[str, Any] | None:
        normalized = json.dumps(changes, sort_keys=True, ensure_ascii=False)
        return next(
            (
                row for row in self.all()
                if row.get("experiment_type") == experiment_type
                and row.get("model_type") == model_type
                and json.dumps(row.get("changes", {}), sort_keys=True, ensure_ascii=False) == normalized
            ),
            None,
        )


class DiagnosisRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "diagnosis_registry.json", "diagnosis_id")


class ApprovalRegistry(JsonRegistry):
    def __init__(self, root: str | Path):
        super().__init__(Path(root) / "approval_registry.json", "approval_id")
