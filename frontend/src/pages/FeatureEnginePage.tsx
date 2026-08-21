import {useEffect,useState} from 'react';
import {Braces,CheckCircle2,Play,RefreshCw,ShieldAlert,Wrench} from 'lucide-react';
import {
  compileFeature,featureCapabilities,featureExecutions,featureGaps,featurePlans,featureSpecs,
  generateFeature,generatedFeatures,getFeatureCredit,getHypothesisCredit,rebuildFeature,
  runFeatureCounterfactual,runFeatureValidation,
} from '../api/client';

type Props={datasetId:string;onError:(message:string)=>void};
const executable=(status:string)=>['SUPPORTED_TEMPLATE','COMPOSABLE_DSL'].includes(status);
const errorText=(e:any)=>String(e?.response?.data?.detail?.message||e?.response?.data?.detail||e?.message||e);
const fmt=(value:any,digits=4)=>typeof value==='number'?value.toFixed(digits):'—';

export default function FeatureEnginePage({datasetId,onError}:Props){
  const [tab,setTab]=useState<'specs'|'plans'|'generated'>('specs');
  const [specs,setSpecs]=useState<any[]>([]),[plans,setPlans]=useState<any[]>([]),[features,setFeatures]=useState<any[]>([]);
  const [executions,setExecutions]=useState<any[]>([]),[gaps,setGaps]=useState<any[]>([]),[capabilities,setCapabilities]=useState<any>(null);
  const [selected,setSelected]=useState<any>(null),[busy,setBusy]=useState('');

  const refresh=async()=>{
    if(!datasetId)return;
    try{
      const [s,p,f,e,g,c]=await Promise.all([featureSpecs(datasetId),featurePlans(datasetId),generatedFeatures(datasetId),featureExecutions(datasetId),featureGaps(datasetId),featureCapabilities()]);
      setSpecs(s.data);setPlans(p.data);setFeatures(f.data);setExecutions(e.data);setGaps(g.data);setCapabilities(c.data);
    }catch(e){onError(errorText(e))}
  };
  useEffect(()=>{refresh()},[datasetId]);

  const act=async(key:string,fn:()=>Promise<any>)=>{
    setBusy(key);
    try{const result=await fn();setSelected(result.data);await refresh()}
    catch(e){onError(errorText(e))}
    finally{setBusy('')}
  };
  const validate=async(feature:any)=>{
    setBusy(`validate-${feature.feature_id}`);
    try{const result=await runFeatureValidation(datasetId,feature.feature_id);setSelected({...feature,status:result.data.decision==='REJECTED'?'REJECTED':'VALIDATED',validation_result:result.data,lr_eligible:result.data.lr_eligible,lgbm_eligible:result.data.lgbm_eligible});await refresh()}
    catch(e){onError(errorText(e))}
    finally{setBusy('')}
  };
  const counterfactual=async(feature:any,model:'LR'|'LGBM',type:'FEATURE_ADD'|'FEATURE_REMOVE'='FEATURE_ADD')=>{
    if(!window.confirm(`Feature: ${feature.feature_name}\nModel: ${model}\nAction: ${type}\nBaseline: current eligible feature pool\nSame Split: YES\nSame Params: YES\nSeed: 42\n\nRun Experiment?`))return;
    setBusy(`${type}-${model}-${feature.feature_id}`);
    try{
      const result=await runFeatureCounterfactual(datasetId,feature.feature_id,model,type);
      const credit=await getFeatureCredit(datasetId,feature.feature_id);
      const hypothesis=result.data.hypothesis_id?await getHypothesisCredit(datasetId,result.data.hypothesis_id):null;
      setSelected({...result.data,feature_credit:credit.data,hypothesis_credit:hypothesis?.data});
      await refresh();
    }catch(e){onError(errorText(e))}
    finally{setBusy('')}
  };

  if(!datasetId)return <div className="empty"><Wrench size={34}/><b>请先导入数据</b><p>Feature Engine 需要已加载的数据集、FeatureSpec 和人工执行确认。</p></div>;
  return <div className="feature-engine-page">
    <div className="page-title"><div><h2>Feature Engine</h2><p>受控 DSL / AST · Cheap Validation · Counterfactual · Feature Credit · Hypothesis Credit</p></div><button className="secondary" onClick={refresh}><RefreshCw size={14}/>刷新</button></div>
    <div className="metrics compact">
      <div className="metric-card"><span>FeatureSpec</span><b>{specs.length}</b><small>Proposal normalization</small></div>
      <div className="metric-card"><span>Compiled</span><b>{plans.length}</b><small>Execution plans</small></div>
      <div className="metric-card tone-a"><span>Validated</span><b>{features.filter(x=>x.status==='VALIDATED').length}</b><small>Not approved</small></div>
      <div className="metric-card tone-review"><span>Capability Gaps</span><b>{gaps.length}</b><small>Explicit requirements</small></div>
      <div className="metric-card"><span>Executions</span><b>{executions.length}</b><small>Audited runs</small></div>
    </div>
    <div className="feature-tabs"><button className={tab==='specs'?'active secondary':'secondary'} onClick={()=>setTab('specs')}>Proposal / Spec</button><button className={tab==='plans'?'active secondary':'secondary'} onClick={()=>setTab('plans')}>Compiled</button><button className={tab==='generated'?'active secondary':'secondary'} onClick={()=>setTab('generated')}>Generated / Validated</button></div>

    {tab==='specs'&&<section className="card"><h3>FeatureSpec Registry</h3>{specs.length?<div className="table-wrap"><table><thead><tr><th>Name</th><th>Type</th><th>Sources</th><th>DSL</th><th>Version</th><th>Action</th></tr></thead><tbody>{specs.map(x=><tr key={x.feature_spec_id}><td><b>{x.feature_name}</b><small>{x.business_intent}</small></td><td>{x.feature_type}</td><td>{x.source_fields?.join(', ')}</td><td><code>{x.dsl_expression||'—'}</code></td><td>{x.version}</td><td><button disabled={!!busy} onClick={()=>act(x.feature_spec_id,()=>compileFeature(datasetId,x.feature_spec_id))}><Braces size={13}/>{busy===x.feature_spec_id?'Compiling':'Compile'}</button></td></tr>)}</tbody></table></div>:<p className="muted">请先在 Analysis Agent 的 Feature Proposal 上点击 Compile。</p>}</section>}

    {tab==='plans'&&<section className="card"><h3>Execution Plans</h3>{plans.length?<div className="engine-grid">{plans.map(x=><article className="engine-card" key={x.plan_id} onClick={()=>setSelected(x)}><span className={`tag ${executable(x.compiler_status)?'tag-a':'tag-review'}`}>{x.compiler_status}</span><b>{specs.find(s=>s.feature_spec_id===x.feature_spec_id)?.feature_name||x.feature_spec_id}</b><code>{x.dsl_expression}</code><small>{x.estimated_cost} cost · {x.operators?.join(', ')||'no operators'}</small>{x.capability_gap&&<div className="warning-box"><ShieldAlert size={14}/>Missing: {[...(x.capability_gap.missing_operator||[]),...(x.capability_gap.missing_data_source||[]),...(x.capability_gap.missing_fields||[])].join(', ')}</div>}{executable(x.compiler_status)&&<button disabled={!!busy} onClick={e=>{e.stopPropagation();if(window.confirm(`Generate feature from ${x.plan_id}?`))act(x.plan_id,()=>generateFeature(datasetId,x.plan_id))}}><Play size={13}/>Generate Feature</button>}</article>)}</div>:<p className="muted">尚无编译计划。</p>}</section>}

    {tab==='generated'&&<section className="card"><h3>Generated Feature Registry</h3>{features.length?<div className="table-wrap"><table><thead><tr><th>Feature</th><th>Status</th><th>Validation</th><th>Version</th><th>Sources</th><th>Actions</th></tr></thead><tbody>{features.map(x=><tr key={x.feature_id} onClick={()=>setSelected(x)} className="clickable"><td><b>{x.feature_name}</b><small>{x.feature_id}</small></td><td><span className="tag tag-a">{x.status}</span></td><td><b>{x.validation_result?.decision||'NOT_RUN'}</b><small>LR {x.lr_eligible?'YES':'NO'} · LGBM {x.lgbm_eligible?'YES':'NO'}</small></td><td>{x.version||x.feature_version}</td><td>{x.source_fields?.join(', ')}</td><td><div className="engine-actions"><button className="secondary" disabled={!!busy} onClick={e=>{e.stopPropagation();act(x.feature_id,()=>rebuildFeature(datasetId,x.feature_id))}}><CheckCircle2 size={13}/>Rebuild</button><button disabled={!!busy||x.status==='REJECTED'} onClick={e=>{e.stopPropagation();validate(x)}}>Run Validation</button>{x.status==='VALIDATED'&&x.lr_eligible&&<><button disabled={!!busy} onClick={e=>{e.stopPropagation();counterfactual(x,'LR')}}>Test in LR</button><button className="secondary" disabled={!!busy} onClick={e=>{e.stopPropagation();counterfactual(x,'LR','FEATURE_REMOVE')}}>Ablate LR</button></>}{x.status==='VALIDATED'&&x.lgbm_eligible&&<><button disabled={!!busy} onClick={e=>{e.stopPropagation();counterfactual(x,'LGBM')}}>Test in LightGBM</button><button className="secondary" disabled={!!busy} onClick={e=>{e.stopPropagation();counterfactual(x,'LGBM','FEATURE_REMOVE')}}>Ablate LGBM</button></>}</div></td></tr>)}</tbody></table></div>:<p className="muted">尚无已生成人工特征。</p>}</section>}

    {capabilities&&<section className="card engine-capabilities"><h3>Capability Registry</h3><p><b>Operators</b> {capabilities.operators.join(', ')}</p><p><b>Windows</b> {capabilities.windows.join(', ')}</p><p><b>Unsupported examples</b> {capabilities.unsupported_examples.join(', ')}</p></section>}
    {selected&&<aside className="drawer"><button className="drawer-close" onClick={()=>setSelected(null)}>×</button><h2>Feature Detail</h2><div className="drawer-rule">{selected.feature_name||selected.plan_id||selected.experiment_id||selected.execution_id}</div><div className="drawer-grid"><b>Compiler Status<small>{selected.compiler_status||'—'}</small></b><b>Execution / Decision<small>{selected.status||selected.decision||'—'}</small></b><b>Estimated Cost<small>{selected.estimated_cost||'—'}</small></b><b>Dataset Version<small>{selected.dataset_version?.slice(0,12)||'—'}</small></b></div>
      {selected.validation_result&&<><h3>Cheap Validation</h3><div className="validation-metrics"><b>Valid<small>{fmt(selected.validation_result.metrics?.valid_rate*100,2)}%</small></b><b>Missing<small>{fmt(selected.validation_result.metrics?.missing_rate*100,2)}%</small></b><b>Lift<small>{fmt(selected.validation_result.metrics?.lift,3)}</small></b><b>IV<small>{fmt(selected.validation_result.metrics?.iv)}</small></b><b>PSI<small>{fmt(selected.validation_result.metrics?.psi)}</small></b><b>Novelty<small>{selected.validation_result.metrics?.feature_novelty||'—'}</small></b><b>Correlation<small>{fmt(selected.validation_result.metrics?.max_existing_correlation,3)}</small></b><b>Eligibility<small>LR {selected.lr_eligible?'YES':'NO'} · LGBM {selected.lgbm_eligible?'YES':'NO'}</small></b></div></>}
      {selected.metrics_before&&<><h3>Counterfactual Before / After</h3><div className="delta-table"><span>OOT AUC</span><b>{fmt(selected.metrics_before.oot_auc)} → {fmt(selected.metrics_after.oot_auc)}</b><em>{selected.delta_metrics.delta_oot_auc>=0?'+':''}{fmt(selected.delta_metrics.delta_oot_auc)}</em><span>OOT KS</span><b>{fmt(selected.metrics_before.oot_ks)} → {fmt(selected.metrics_after.oot_ks)}</b><em>{selected.delta_metrics.delta_oot_ks>=0?'+':''}{fmt(selected.delta_metrics.delta_oot_ks)}</em><span>Lift@10</span><b>{fmt(selected.metrics_before.lift_at_10,3)} → {fmt(selected.metrics_after.lift_at_10,3)}</b><em>{selected.delta_metrics.delta_lift_10>=0?'+':''}{fmt(selected.delta_metrics.delta_lift_10,3)}</em><span>AUC Gap</span><b>{fmt(selected.metrics_before.train_oot_auc_gap)} → {fmt(selected.metrics_after.train_oot_auc_gap)}</b><em>{fmt(selected.delta_metrics.delta_auc_gap)}</em><span>Score PSI</span><b>{fmt(selected.metrics_before.score_psi)} → {fmt(selected.metrics_after.score_psi)}</b><em>{fmt(selected.delta_metrics.delta_score_psi)}</em></div><p className="experiment-guard">Same Split: YES · Same Params: YES · Seed: {selected.seed}</p></>}
      {selected.feature_credit&&<><h3>Feature Credit</h3>{selected.feature_credit.map((credit:any)=><div className="credit-card" key={credit.credit_id}><b>{credit.model_type}: {credit.overall_direction}</b><span>Performance {credit.performance_credit} · Stability {credit.stability_credit}</span><span>Drift {credit.drift_penalty} penalty · Confidence {credit.confidence}</span>{credit.simplification_candidate&&<em>Simplification Candidate</em>}</div>)}</>}
      {selected.hypothesis_credit&&<><h3>Hypothesis Credit</h3><div className="credit-card"><b>{selected.hypothesis_credit.support_status}</b><span>Positive {selected.hypothesis_credit.positive_features?.length||0} · Neutral {selected.hypothesis_credit.neutral_features?.length||0} · Negative {selected.hypothesis_credit.negative_features?.length||0}</span><span>Best ΔAUC {fmt(selected.hypothesis_credit.best_delta_auc)} · Best ΔKS {fmt(selected.hypothesis_credit.best_delta_ks)}</span></div></>}
      <h3>DSL / Human Formula</h3><code>{selected.dsl_expression||selected.human_formula||'—'}</code><h3>AST / Lineage / Audit</h3><pre className="json-detail">{JSON.stringify(selected,null,2)}</pre>
    </aside>}
  </div>;
}
