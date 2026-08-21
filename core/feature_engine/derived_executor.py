from __future__ import annotations

import numpy as np
import pandas as pd
from .ast import ConstantNode, OperatorNode
from .exceptions import ExecutionFailed


class DerivedExecutor:
    OPS={"RULE_GROUP_HIT","RULE_GROUP_HIT_COUNT"}
    def __init__(self,rules:list[dict]|None=None):self.rules=rules or []
    def execute(self,node:OperatorNode,df:pd.DataFrame):
        if node.op not in self.OPS:return None
        if not node.args or not isinstance(node.args[0],ConstantNode):raise ExecutionFailed("Rule group ID must be a constant")
        group=str(node.args[0].value);members=[x for x in self.rules if str(x.get("rule_group_id"))==group and x.get("_mask_global") is not None]
        if not members:raise ExecutionFailed(f"Rule group artifact missing: {group}")
        masks=np.vstack([np.asarray(x["_mask_global"],dtype=bool)[:len(df)] for x in members])
        values=masks.any(axis=0).astype(int) if node.op=="RULE_GROUP_HIT" else masks.sum(axis=0)
        return pd.Series(values,index=df.index)
