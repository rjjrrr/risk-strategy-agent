from __future__ import annotations

import hashlib
import json
from typing import Any

from core.json_utils import sanitize_json


FORBIDDEN_MEMORY_KEYS = {"raw_rows", "rows", "dataframe", "df", "records", "raw_data"}


def stable_hash(value: Any) -> str:
    encoded = json.dumps(sanitize_json(value), sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def assert_no_raw_data(value: Any) -> None:
    if isinstance(value, dict):
        bad = FORBIDDEN_MEMORY_KEYS.intersection(key.lower() for key in value)
        if bad:
            raise ValueError(f"Experiment Memory cannot contain raw data keys: {sorted(bad)}")
        for item in value.values():
            assert_no_raw_data(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_raw_data(item)
