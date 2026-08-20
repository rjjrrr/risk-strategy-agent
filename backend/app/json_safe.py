"""Strict JSON normalization shared by every FastAPI JSON response."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse
from core.json_utils import sanitize_json


class SafeJSONResponse(JSONResponse):
    """Final safety net for NaN/Infinity produced by any API endpoint."""

    def render(self, content: Any) -> bytes:
        return super().render(sanitize_json(content))
