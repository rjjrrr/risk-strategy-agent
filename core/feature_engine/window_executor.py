from __future__ import annotations

import numpy as np
import pandas as pd
from .ast import FieldNode, OperatorNode, WindowNode
from .capability import FeatureCapabilityRegistry
from .exceptions import ExecutionFailed


class WindowExecutor:
    OPS={"COUNT_OVER_WINDOW","SUM_OVER_WINDOW","MEAN_OVER_WINDOW","NUNIQUE_OVER_WINDOW","ENTITY_WINDOW_COUNT","ENTITY_WINDOW_NUNIQUE","CONDITIONAL_COUNT","CONDITIONAL_NUNIQUE"}
    def __init__(self,capabilities=None):self.capabilities=capabilities or FeatureCapabilityRegistry()

    @staticmethod
    def _field(node):
        if not isinstance(node,FieldNode):raise ExecutionFailed("Window field arguments must be field names")
        return node.name
    @staticmethod
    def _window(node):
        if not isinstance(node,WindowNode):raise ExecutionFailed("Window argument must be a quoted supported duration")
        return node.value

    def execute(self,node:OperatorNode,df:pd.DataFrame,evaluate=None):
        if node.op not in self.OPS:return None
        entity=self._field(node.args[0])
        count_op=node.op in {"COUNT_OVER_WINDOW","ENTITY_WINDOW_COUNT","CONDITIONAL_COUNT"}
        conditional=node.op in {"CONDITIONAL_COUNT","CONDITIONAL_NUNIQUE"}
        if node.op=="CONDITIONAL_COUNT":time_field=self._field(node.args[1]);value_field=None;condition_node=node.args[2];window=self._window(node.args[3])
        elif node.op=="CONDITIONAL_NUNIQUE":value_field=self._field(node.args[1]);time_field=self._field(node.args[2]);condition_node=node.args[3];window=self._window(node.args[4])
        elif count_op:time_field=self._field(node.args[1]);value_field=None;condition_node=None;window=self._window(node.args[2])
        else:value_field=self._field(node.args[1]);time_field=self._field(node.args[2]);condition_node=None;window=self._window(node.args[3])
        if not self.capabilities.supports_window(window):raise ExecutionFailed(f"Unsupported window: {window}")
        needed={entity,time_field}|({value_field} if value_field else set())
        missing=needed-set(df.columns)
        if missing:raise ExecutionFailed(f"Window source fields missing: {sorted(missing)}")
        work=pd.DataFrame({"_entity":df[entity],"_time":pd.to_datetime(df[time_field],errors="coerce"),"_position":np.arange(len(df))},index=df.index)
        if value_field:work["_value"]=df[value_field]
        if conditional:
            if evaluate is None:raise ExecutionFailed("Conditional window requires a controlled condition evaluator")
            work["_condition"]=pd.Series(evaluate(condition_node),index=df.index).fillna(False).astype(bool)
        result=pd.Series(np.nan,index=df.index,dtype=float);valid=work["_entity"].notna()&work["_time"].notna();subset=work.loc[valid]
        if subset.empty:return result
        def calculate(group):
            ordered=group.sort_values(["_time","_position"],kind="stable");time_index=pd.DatetimeIndex(ordered["_time"])
            if count_op:
                source=ordered["_condition"].astype(float).to_numpy() if conditional else np.ones(len(ordered),dtype=float)
                values=pd.Series(source,index=time_index).rolling(window,closed="left").sum().to_numpy()
            elif node.op in {"SUM_OVER_WINDOW"}:
                numeric=pd.to_numeric(ordered["_value"],errors="coerce");values=pd.Series(numeric.to_numpy(),index=time_index).rolling(window,closed="left").sum().to_numpy()
            elif node.op in {"MEAN_OVER_WINDOW"}:
                numeric=pd.to_numeric(ordered["_value"],errors="coerce");values=pd.Series(numeric.to_numpy(),index=time_index).rolling(window,closed="left").mean().to_numpy()
            else:
                raw=ordered["_value"].where(ordered["_condition"]) if conditional else ordered["_value"]
                codes=pd.Series(pd.factorize(raw,sort=False)[0].astype(float),index=time_index);codes=codes.mask(codes<0,np.nan);values=codes.rolling(window,closed="left").apply(lambda x:float(len(np.unique(x[~np.isnan(x)]))),raw=True).to_numpy()
            return pd.Series(values,index=ordered.index)
        # Iterate entity groups, never individual rows. Each group uses pandas'
        # vectorized time rolling with a strict open right boundary.
        parts=[calculate(group) for _,group in subset.groupby("_entity",sort=False)]
        calculated=pd.concat(parts).fillna(0.0) if parts else pd.Series(dtype=float)
        result.loc[calculated.index]=calculated.astype(float)
        return result
