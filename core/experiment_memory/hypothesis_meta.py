def hypothesis_pattern_credit(rows: list[dict], dataset_id: str | None = None) -> list[dict]:
    from .aggregator import CreditAggregator
    return CreditAggregator().aggregate(rows, "HYPOTHESIS_PATTERN", by_model=True, dataset_id=dataset_id)
