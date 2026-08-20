from typing import Optional
from pydantic import BaseModel
class RuleQuery(BaseModel):
    segment: Optional[str] = None
