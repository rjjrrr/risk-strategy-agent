from __future__ import annotations

import hashlib
import json
from typing import Any
from core.json_utils import sanitize_json


def stable_json(value: Any) -> str:
    return json.dumps(sanitize_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def estimate_tokens(value: Any) -> int:
    # Conservative dependency-free estimate suitable for budget enforcement.
    text = value if isinstance(value, str) else stable_json(value)
    ascii_count = sum(ord(char) < 128 for char in text)
    return max(1, int((ascii_count / 4) + (len(text) - ascii_count) * 0.8) + 1)
