from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.feature_engine.audit import CapabilityGapRegistry,ExecutionPlanRegistry,FeatureExecutionRegistry,FeatureSpecRegistry
from core.feature_engine.capability import FeatureCapabilityRegistry
from core.feature_engine.compiler import FeatureCompiler
from core.feature_engine.exceptions import ExecutionFailed,FeatureEngineError,RebuildMismatch
from core.feature_engine.executor import FeatureExecutor
from core.feature_engine.lineage import dataset_version
from core.feature_engine.normalizer import normalize_proposal
from core.feature_engine.rebuild import compare_values
from core.feature_engine.registry_adapter import FeatureRegistryAdapter
from core.feature_engine.schemas import FeatureExecutionPlan,FeatureExecutionResult,FeatureSpec,utc_now
from core.json_utils import sanitize_json
from core.model_agent.registry import FeatureRegistry
from .. import config
from .analysis_service import DATASETS
from . import agent_chat_service,context_service

capabilities=FeatureCapabilityRegistry();compiler=FeatureCompiler(capabilities);executor=FeatureExecutor()


def _dataset(dataset_id:str)->dict[str,Any]:
    if dataset_id not in DATASETS:raise KeyError(f"Dataset not loaded: {dataset_id}")
    return DATASETS[dataset_id]
def _root(dataset_id:str)->Path:
    root=config.MODEL_AGENT_DIR/dataset_id;root.mkdir(parents=True,exist_ok=True);return root
def _governance(ds):
    rows=ds.get('governance')
    if rows is None:return {}
    values=rows.to_dict('records') if hasattr(rows,'to_dict') else rows
    return {str(x.get('field')):x for x in values}
def _artifact_dir(dataset_id):
    path=_root(dataset_id)/'feature_store';path.mkdir(parents=True,exist_ok=True);return path
def _find(registry,identifier):
    row=registry.get(identifier)
    if not row:raise KeyError(identifier)
    return row


def capability_summary():return capabilities.summary()


def feature_specs(dataset_id:str):return FeatureSpecRegistry(_root(dataset_id)).all()
def feature_spec(dataset_id:str,spec_id:str):return _find(FeatureSpecRegistry(_root(dataset_id)),spec_id)
def plans(dataset_id:str):return ExecutionPlanRegistry(_root(dataset_id)).all()
def plan(dataset_id:str,plan_id:str):return _find(ExecutionPlanRegistry(_root(dataset_id)),plan_id)
def executions(dataset_id:str):return FeatureExecutionRegistry(_root(dataset_id)).all()
def execution(dataset_id:str,execution_id:str):return _find(FeatureExecutionRegistry(_root(dataset_id)),execution_id)
def gaps(dataset_id:str):return CapabilityGapRegistry(_root(dataset_id)).all()
def generated_features(dataset_id:str):return FeatureRegistry(_root(dataset_id)).all()


def spec_from_proposal(dataset_id:str,proposal_id:str)->dict:
    ds=_dataset(dataset_id);proposal=agent_chat_service.store.proposal(proposal_id)
    if proposal.get('proposal_type')!='FEATURE_CANDIDATE':raise ValueError('Only FEATURE_CANDIDATE can become FeatureSpec')
    conversation=agent_chat_service.store.conversation(proposal['conversation_id'])
    if conversation.get('dataset_id')!=dataset_id:raise ValueError('Proposal does not belong to this dataset')
    if proposal.get('status') in {'REJECTED','REJECTED_BY_USER'}:raise ValueError('Rejected proposal cannot become FeatureSpec')
    registry=FeatureSpecRegistry(_root(dataset_id));existing=next((row for row in registry.all() if row.get('proposal_id')==proposal_id),None)
    if existing:return existing
    payload={**proposal['payload'],'proposal_id':proposal_id};spec=normalize_proposal(payload,dataset_id,dataset_version(ds['df']))
    registry.add(spec.model_dump());return spec.model_dump()


def create_spec(dataset_id:str,payload:dict[str,Any])->dict:
    ds=_dataset(dataset_id)
    if payload.get('feature_spec_id'):spec=FeatureSpec.model_validate({**payload,'dataset_id':dataset_id,'dataset_version':dataset_version(ds['df'])})
    else:spec=normalize_proposal(payload,dataset_id,dataset_version(ds['df']))
    FeatureSpecRegistry(_root(dataset_id)).add(spec.model_dump());return spec.model_dump()


def compile_spec(dataset_id:str,spec_id:str,available_sources:list[str]|None=None)->dict:
    ds=_dataset(dataset_id);root=_root(dataset_id);spec=FeatureSpec.model_validate(feature_spec(dataset_id,spec_id));current_version=dataset_version(ds['df'])
    if spec.dataset_version!=current_version:spec=spec.model_copy(update={'dataset_version':current_version})
    available=set(available_sources or ['CURRENT_WIDE_TABLE'])
    result=compiler.compile(spec,schema_fields={str(x) for x in ds['df'].columns},governance=_governance(ds),available_sources=available,feature_registry=FeatureRegistry(root).all())
    ExecutionPlanRegistry(root).add(result.model_dump())
    if result.capability_gap:CapabilityGapRegistry(root).add(result.capability_gap.model_dump())
    return result.model_dump()


def compile_payload(dataset_id:str,payload:dict[str,Any])->dict:
    spec_id=payload.get('feature_spec_id')
    if not spec_id:spec_id=create_spec(dataset_id,payload.get('feature_spec') or payload)['feature_spec_id']
    return compile_spec(dataset_id,spec_id,payload.get('available_data_sources'))


def _save_values(dataset_id:str,feature_id:str,version:str,values:pd.Series)->str:
    path=_artifact_dir(dataset_id)/f"{feature_id}__v{version}.npz";np.savez_compressed(path,values=values.to_numpy(),index=values.index.to_numpy());return str(path)
def _load_values(path:str)->pd.Series:
    data=np.load(path,allow_pickle=True);return pd.Series(data['values'],index=data['index'])


def execute_plan(dataset_id:str,plan_id:str,*,user_confirmed:bool=False)->dict:
    if not user_confirmed:raise ValueError('Explicit user confirmation is required to generate a feature')
    ds=_dataset(dataset_id);root=_root(dataset_id);plan_obj=FeatureExecutionPlan.model_validate(plan(dataset_id,plan_id));spec=FeatureSpec.model_validate(feature_spec(dataset_id,plan_obj.feature_spec_id));execution_id=f"FX_{uuid.uuid4().hex[:12]}";started=utc_now();audit=FeatureExecutionRegistry(root)
    initial=FeatureExecutionResult(execution_id=execution_id,dataset_id=dataset_id,plan_id=plan_id,status='RUNNING',started_at=started,dataset_version=dataset_version(ds['df']));audit.add(initial.model_dump())
    if not plan_obj.executable:
        row=audit.update(execution_id,status='BLOCKED',finished_at=utc_now(),error_type='OPERATOR_UNSUPPORTED',error_summary=f"Compiler status: {plan_obj.compiler_status}",success=False);return row
    try:
        values=executor.execute(spec,plan_obj,ds['df'],rules=ds.get('rules',[]));from core.feature_engine.validator import validate_values
        sanity=validate_values(values);version_rows=FeatureRegistry(root).all();major=max([int(str(x.get('version') or x.get('feature_version','0')).split('.')[0]) for x in version_rows if x.get('feature_name')==spec.feature_name] or [0])+1;version=f"{major}.0";temporary_id=f"F_GEN_{uuid.uuid4().hex[:10]}";artifact=_save_values(dataset_id,temporary_id,version,values)
        adapter=FeatureRegistryAdapter(root);feature=adapter.add_generated(spec,plan_obj,artifact_path=artifact,execution_id=execution_id)
        final_path=_artifact_dir(dataset_id)/f"{feature['feature_id']}__v{feature['version']}.npz";Path(artifact).replace(final_path);FeatureRegistry(root).update(feature['feature_id'],artifact_path=str(final_path));feature['artifact_path']=str(final_path)
        row=audit.update(execution_id,feature_id=feature['feature_id'],status='SUCCESS',finished_at=utc_now(),rows=sanity['rows'],valid_count=sanity['valid_count'],missing_count=sanity['missing_count'],missing_rate=sanity['missing_rate'],statistics=sanity['statistics'],success=True,artifact_path=str(final_path),validation_status='NOT_RUN',dataset_version=spec.dataset_version)
        context_service._cache.clear();return {**row,'feature':feature,'sanity':sanity}
    except Exception as exc:
        code=getattr(exc,'code','EXECUTION_FAILED');audit.update(execution_id,status='FAILED',finished_at=utc_now(),success=False,error_type=code,error_summary=str(exc)[:300]);raise ExecutionFailed(str(exc)) from exc


def rebuild_feature(dataset_id:str,feature_id:str)->dict:
    ds=_dataset(dataset_id);root=_root(dataset_id);feature=_find(FeatureRegistry(root),feature_id);spec=FeatureSpec.model_validate(feature_spec(dataset_id,feature['feature_spec_id']));plan_obj=FeatureExecutionPlan.model_validate(plan(dataset_id,feature['execution_plan_id']));current=dataset_version(ds['df']);rebuilt=executor.execute(spec,plan_obj,ds['df'],rules=ds.get('rules',[]));original=_load_values(feature['artifact_path']);match,method=compare_values(original,rebuilt);version_match=current==feature.get('dataset_version');execution_id=f"FXR_{uuid.uuid4().hex[:12]}";status='SUCCESS' if match and version_match else 'FAILED';error=None if status=='SUCCESS' else 'REBUILD_MISMATCH' if version_match else 'DATASET_VERSION_MISMATCH'
    row=FeatureExecutionResult(execution_id=execution_id,feature_id=feature_id,dataset_id=dataset_id,plan_id=plan_obj.plan_id,status=status,started_at=utc_now(),finished_at=utc_now(),rows=len(rebuilt),valid_count=int(rebuilt.notna().sum()),missing_count=int(rebuilt.isna().sum()),missing_rate=float(rebuilt.isna().mean()) if len(rebuilt) else 0,statistics={'comparison_method':method,'values_match':match,'dataset_version_match':version_match,'stored_dataset_version':feature.get('dataset_version'),'current_dataset_version':current},success=status=='SUCCESS',error_type=error,error_summary=None if not error else 'Rebuild cannot claim exact reproduction',artifact_path=feature.get('artifact_path'),dataset_version=current)
    FeatureExecutionRegistry(root).add(row.model_dump())
    return row.model_dump()
