from __future__ import annotations

import pandas as pd
from .ast import OperatorNode, from_dict
from .column_executor import ColumnExecutor
from .derived_executor import DerivedExecutor
from .entity_executor import EntityExecutor
from .exceptions import ExecutionFailed
from .schemas import FeatureExecutionPlan, FeatureSpec
from .window_executor import WindowExecutor


class FeatureExecutor:
    def __init__(self,zero_denominator_policy="MISSING"):self.column=ColumnExecutor(zero_denominator_policy);self.window=WindowExecutor();self.entity=EntityExecutor()
    def execute(self,spec:FeatureSpec,plan:FeatureExecutionPlan,df:pd.DataFrame,*,rules=None)->pd.Series:
        if not plan.executable or not plan.ast:raise ExecutionFailed(f"Plan is not executable: {plan.compiler_status}")
        node=from_dict(plan.ast);derived=DerivedExecutor(rules)
        def delegate(current,frame):
            if not isinstance(current,OperatorNode):return None
            return self.window.execute(current,frame,lambda condition:self.column.execute(condition,frame,delegate)) if current.op in self.window.OPS else self.entity.execute(current,frame) if current.op in self.entity.OPS else derived.execute(current,frame) if current.op in derived.OPS else None
        values=self.column.execute(node,df,delegate)
        return values if isinstance(values,pd.Series) else pd.Series(values,index=df.index)
