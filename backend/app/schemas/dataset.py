from typing import Literal, Optional
from pydantic import BaseModel
class RunRequest(BaseModel):
    target: str = "target7"
    segment_field: str = "is_old"
    application_time_field: Optional[str] = None
    bad_label: int = 1
    good_label: int = 0
    mode: Literal["CURRENT", "FROM_HERE"] = "CURRENT"
    same_group_jaccard: float = 0.90
    similar_jaccard: float = 0.80
class RunAllRequest(RunRequest):
    force: bool = False
