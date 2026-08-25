from __future__ import annotations

import numpy as np
import pandas as pd
from .ast import ConditionNode, ConstantNode, FieldNode, Node, OperatorNode, WindowNode
from .exceptions import ExecutionFailed
from .operators import apply_condition, safe_divide


class ColumnExecutor:
    def __init__(self,zero_denominator_policy="MISSING"):self.zero_denominator_policy=zero_denominator_policy

    def execute(self,node:Node,df:pd.DataFrame,delegate=None):
        index=df.index
        if isinstance(node,FieldNode):
            if node.name not in df:raise ExecutionFailed(f"Source field missing at execution: {node.name}")
            return df[node.name]
        if isinstance(node,ConstantNode):return node.value
        if isinstance(node,WindowNode):return node.value
        if isinstance(node,ConditionNode):
            values=[self.execute(x,df,delegate) for x in node.args]
            if node.op=="NOT":return ~pd.Series(values[0],index=index).fillna(False).astype(bool)
            if node.op=="BOOLEAN_AND":
                result=pd.Series(True,index=index)
                for value in values:result=result & pd.Series(value,index=index).fillna(False).astype(bool)
                return result
            if node.op=="BOOLEAN_OR":
                result=pd.Series(False,index=index)
                for value in values:result=result | pd.Series(value,index=index).fillna(False).astype(bool)
                return result
            return apply_condition(node.op,values[0],values[1],index)
        if not isinstance(node,OperatorNode):raise ExecutionFailed("Unknown execution node")
        if delegate is not None:
            delegated=delegate(node,df)
            if delegated is not None:return delegated
        args=[self.execute(x,df,delegate) for x in node.args];op=node.op
        if op in {"EQ","NE","GT","GE","LT","LE","IN"}:return apply_condition(op,args[0],args[1],index)
        if op=="NOT":return ~pd.Series(args[0],index=index).fillna(False).astype(bool)
        if op in {"BOOLEAN_AND","BOOLEAN_OR"}:
            result=pd.Series(True if op=="BOOLEAN_AND" else False,index=index)
            for value in args:result=(result & pd.Series(value,index=index).fillna(False).astype(bool)) if op=="BOOLEAN_AND" else (result | pd.Series(value,index=index).fillna(False).astype(bool))
            return result
        if op=="SAFE_DIV":return safe_divide(args[0],args[1],index,self.zero_denominator_policy)
        if op=="ADD":return pd.to_numeric(pd.Series(args[0],index=index),errors="coerce")+pd.to_numeric(pd.Series(args[1],index=index),errors="coerce")
        if op=="SUB":return pd.to_numeric(pd.Series(args[0],index=index),errors="coerce")-pd.to_numeric(pd.Series(args[1],index=index),errors="coerce")
        if op=="MUL":return pd.to_numeric(pd.Series(args[0],index=index),errors="coerce")*pd.to_numeric(pd.Series(args[1],index=index),errors="coerce")
        if op=="MOD":
            left=pd.to_numeric(pd.Series(args[0],index=index),errors="coerce");right=pd.to_numeric(pd.Series(args[1],index=index),errors="coerce")
            return left.mod(right.mask(right==0,np.nan)).replace([np.inf,-np.inf],np.nan)
        if op=="POWER":
            base=pd.to_numeric(pd.Series(args[0],index=index),errors="coerce");exponent=pd.to_numeric(pd.Series(args[1],index=index),errors="coerce").clip(-10,10)
            with np.errstate(over="ignore",invalid="ignore",divide="ignore"):result=np.power(base,exponent)
            return pd.Series(result,index=index).replace([np.inf,-np.inf],np.nan)
        if op=="ABS":return pd.to_numeric(pd.Series(args[0],index=index),errors="coerce").abs()
        if op=="SIGN":return np.sign(pd.to_numeric(pd.Series(args[0],index=index),errors="coerce"))
        if op=="SQRT":
            values=pd.to_numeric(pd.Series(args[0],index=index),errors="coerce");return pd.Series(np.where(values>=0,np.sqrt(values),np.nan),index=index)
        if op=="EXP":
            values=pd.to_numeric(pd.Series(args[0],index=index),errors="coerce");return pd.Series(np.exp(values.clip(-50,50)),index=index)
        if op=="MIN":return pd.concat([pd.Series(args[0],index=index),pd.Series(args[1],index=index)],axis=1).min(axis=1,skipna=False)
        if op=="MAX":return pd.concat([pd.Series(args[0],index=index),pd.Series(args[1],index=index)],axis=1).max(axis=1,skipna=False)
        if op=="CLIP":return pd.to_numeric(pd.Series(args[0],index=index),errors="coerce").clip(lower=args[1],upper=args[2])
        if op=="ROUND":return pd.to_numeric(pd.Series(args[0],index=index),errors="coerce").round(int(args[1]) if len(args)>1 else 0)
        if op=="FLOOR":return np.floor(pd.to_numeric(pd.Series(args[0],index=index),errors="coerce"))
        if op=="CEIL":return np.ceil(pd.to_numeric(pd.Series(args[0],index=index),errors="coerce"))
        if op=="LOG1P":
            values=pd.to_numeric(pd.Series(args[0],index=index),errors="coerce");return pd.Series(np.where(values>=-1,np.log1p(values),np.nan),index=index)
        if op in {"IS_MISSING","MISSING_FLAG"}:return pd.Series(args[0],index=index).isna().astype(int)
        if op=="COALESCE":
            result=pd.Series(args[0],index=index)
            for value in args[1:]:result=result.fillna(pd.Series(value,index=index))
            return result
        if op=="IF":return pd.Series(np.where(pd.Series(args[0],index=index).fillna(False),args[1],args[2]),index=index)
        if op=="TIME_DIFF":return (pd.to_datetime(args[0],errors="coerce")-pd.to_datetime(args[1],errors="coerce")).dt.total_seconds()
        if op in {"DAYS_BETWEEN","HOURS_BETWEEN"}:
            seconds=(pd.to_datetime(args[0],errors="coerce")-pd.to_datetime(args[1],errors="coerce")).dt.total_seconds()
            return seconds/(86400 if op=="DAYS_BETWEEN" else 3600)
        if op in {"HOUR","DAY_OF_WEEK","DAY_OF_MONTH","MONTH","IS_WEEKEND"}:
            values=pd.to_datetime(args[0],errors="coerce")
            if op=="HOUR":return values.dt.hour.astype("float")
            if op=="DAY_OF_WEEK":return values.dt.dayofweek.astype("float")
            if op=="DAY_OF_MONTH":return values.dt.day.astype("float")
            if op=="MONTH":return values.dt.month.astype("float")
            return values.dt.dayofweek.isin([5,6]).astype(int)
        if op in {"COUNT","SUM","MEAN","MEDIAN","MIN_AGG","MAX_AGG","STD","NUNIQUE"}:
            values=pd.Series(args[0],index=index)
            aggregate={"COUNT":values.count,"SUM":values.sum,"MEAN":values.mean,"MEDIAN":values.median,"MIN_AGG":values.min,"MAX_AGG":values.max,"STD":lambda:values.std(ddof=0),"NUNIQUE":values.nunique}[op]()
            return pd.Series(aggregate,index=index)
        raise ExecutionFailed(f"Operator has no column implementation: {op}")
