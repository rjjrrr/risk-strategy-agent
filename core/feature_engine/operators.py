from __future__ import annotations

import numpy as np
import pandas as pd


def _series(value,index):return value if isinstance(value,pd.Series) else pd.Series(value,index=index)


def safe_divide(numerator,denominator,index,policy="MISSING",epsilon=1e-8):
    left=pd.to_numeric(_series(numerator,index),errors="coerce");right=pd.to_numeric(_series(denominator,index),errors="coerce")
    if policy=="EPSILON":result=left/right.mask(right==0,epsilon)
    elif policy=="ZERO":result=(left/right.mask(right==0,np.nan)).fillna(0)
    else:result=left/right.mask(right==0,np.nan)
    return result.replace([np.inf,-np.inf],np.nan)


def apply_condition(op,left,right,index):
    left=_series(left,index)
    if op=="EQ":return left.eq(right)
    if op=="NE":return left.ne(right)
    if op=="GT":return left.gt(right)
    if op=="GE":return left.ge(right)
    if op=="LT":return left.lt(right)
    if op=="LE":return left.le(right)
    if op=="IN":return left.isin(right if isinstance(right,list) else [right])
    raise ValueError(op)
