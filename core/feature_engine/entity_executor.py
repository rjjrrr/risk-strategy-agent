from __future__ import annotations

import pandas as pd
from .ast import FieldNode, OperatorNode
from .exceptions import ExecutionFailed


class EntityExecutor:
    OPS={"ENTITY_COUNT","ENTITY_NUNIQUE"}
    @staticmethod
    def _field(node):
        if not isinstance(node,FieldNode):raise ExecutionFailed("Entity arguments must be field names")
        return node.name
    def execute(self,node:OperatorNode,df:pd.DataFrame):
        if node.op not in self.OPS:return None
        entity=self._field(node.args[0])
        if entity not in df:raise ExecutionFailed(f"Entity field missing: {entity}")
        if node.op=="ENTITY_COUNT":return df.groupby(entity,dropna=False)[entity].transform("size").astype(float)
        target=self._field(node.args[1])
        if target not in df:raise ExecutionFailed(f"Entity target field missing: {target}")
        return df.groupby(entity,dropna=False)[target].transform("nunique").astype(float)
