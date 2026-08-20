from typing import Literal
from pydantic import BaseModel
class GovernancePatch(BaseModel):
    decision: Literal["KEEP", "EXCLUDE", "SUSPECT_LEAKAGE", "IDENTIFIER", "REVIEW"]
