from fastapi import APIRouter, HTTPException
from ..schemas.governance import GovernancePatch
from ..services.analysis_service import patch_governance
router=APIRouter(prefix="/api/analysis",tags=["governance"])
@router.patch("/{dataset_id}/governance/{field}")
def patch(dataset_id:str,field:str,body:GovernancePatch):
    try: return patch_governance(dataset_id,field,body.decision)
    except Exception as e: raise HTTPException(400,str(e))
