def feature_type_credit(rows: list[dict], dataset_id: str | None = None) -> list[dict]:
    from .aggregator import CreditAggregator
    return CreditAggregator().aggregate(rows, "FEATURE_TYPE", dataset_id=dataset_id)
