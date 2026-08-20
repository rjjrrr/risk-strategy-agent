from typing import Optional
from fastapi import APIRouter, HTTPException
from ..services.analysis_service import get_dataset
from .analysis import _public_rules
router=APIRouter(prefix="/api/analysis",tags=["rules"])
@router.get("/{dataset_id}/rules")
def rules(dataset_id:str,segment:Optional[str]=None,grade:Optional[str]=None,field:Optional[str]=None,min_lift:Optional[float]=None,min_coverage:Optional[float]=None,representative_only:bool=True,sort_by:str="lift"):
    try: rows=get_dataset(dataset_id)["rules"]
    except Exception as e: raise HTTPException(404,str(e))
    if segment: rows=[x for x in rows if x.get("segment")==segment]
    if grade: rows=[x for x in rows if x.get("grade")==grade]
    if field: rows=[x for x in rows if x.get("field")==field]
    if min_lift is not None: rows=[x for x in rows if x.get("lift",0)>=min_lift]
    if min_coverage is not None: rows=[x for x in rows if x.get("coverage",0)>=min_coverage]
    if representative_only: rows=[x for x in rows if x.get("is_representative",True)]
    return sorted(_public_rules(rows),key=lambda x:x.get(sort_by,0) or 0,reverse=True)
@router.get("/{dataset_id}/variables/{field}")
def variable(dataset_id:str,field:str):
    ds=get_dataset(dataset_id); meta=ds["governance"]
    if meta is None: raise HTTPException(400,"请先执行字段治理")
    hit=meta[meta.field==field]
    if hit.empty: raise HTTPException(404,"field不存在")
    return {"field":field,"governance":hit.iloc[0].where(hit.iloc[0].notna(),None).to_dict(),"rules":_public_rules([x for x in ds["rules"] if x.get("field")==field])}
