from datetime import datetime, timezone
import math
import numpy as np
import pandas as pd
from fastapi import APIRouter, UploadFile, File, HTTPException
from ..services.analysis_service import register_upload, get_dataset
router=APIRouter(prefix="/api/datasets",tags=["datasets"])

def _json_safe(value):
    if value is None: return None
    if isinstance(value, dict): return {str(k):_json_safe(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [_json_safe(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)): return value.isoformat()
    if isinstance(value, (float, np.floating)) and not math.isfinite(float(value)): return None
    if isinstance(value, np.generic): return value.item()
    return value
@router.post("/upload")
async def upload(file: UploadFile=File(...)):
    try:
        content=await file.read(); did,df=register_upload(file.filename or "data.csv",content)
        preview=df.head(20).to_dict(orient="records")
        return _json_safe({"dataset_id":did,"filename":file.filename,"file_size":len(content),"uploaded_at":datetime.now(timezone.utc).isoformat(),"rows":len(df),"columns":len(df.columns),"column_names":df.columns.tolist(),"dtypes":{k:str(v) for k,v in df.dtypes.items()},"preview":preview})
    except Exception as e: raise HTTPException(400,str(e))
@router.get("/{dataset_id}/summary")
def summary(dataset_id:str):
    try:
        df=get_dataset(dataset_id)["df"]; result={"row_count":len(df),"column_count":len(df.columns)}
        if "is_old" in df: result.update({"NEW_count":int((df.is_old==0).sum()),"OLD_count":int((df.is_old==2).sum())})
        if "target7" in df and "is_old" in df:
            for s,v in [("NEW",0),("OLD",2)]:
                x=df[df.is_old==v].target7; result[f"{s}_bad_rate"]=float(x.mean()) if len(x) else None
        return result
    except KeyError as e: raise HTTPException(404,str(e))
