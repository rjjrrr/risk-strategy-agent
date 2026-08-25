from __future__ import annotations

from .similarity import similarity_score


class ExperimentRetriever:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def similar(self, query: dict, limit: int = 5) -> list[dict]:
        ranked = sorted(self.rows, key=lambda row: (-similarity_score(query, row), str(row.get("timestamp") or "")), reverse=False)
        output = []
        for row in ranked[:max(0, min(limit, 20))]:
            output.append({**row, "similarity_score": similarity_score(query, row), "scope": "SAME_DATASET" if row.get("dataset_id") == query.get("dataset_id") else "GLOBAL_REFERENCE"})
        return output

    def context(self, query: dict) -> dict:
        similar = self.similar(query, 20)
        winners = [x for x in similar if x.get("counterfactual_decision") == "POSITIVE"][:5]
        failures = [x for x in similar if x.get("counterfactual_decision") in {"NEGATIVE", "NEUTRAL", "UNSTABLE", "FAILED"}][:5]
        return {"similar": similar[:5], "historical_winners": winners, "relevant_failures": failures}
