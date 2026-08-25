import {useEffect,useState} from 'react';
import {Braces,CheckCircle2,Play,RefreshCw,ShieldAlert,Wrench} from 'lucide-react';
import {
  compileFeature,featureCapabilities,featureExecutions,featureGaps,featurePlans,featureSpecs,
  generateFeature,generatedFeatures,getFeatureCredit,getHypothesisCredit,rebuildFeature,
  runFeatureCounterfactual,runFeatureValidation,
} from '../api/client';
import {BusinessLabel,MetricHelp} from '../components/BusinessLabel';
import {creditLabels,validationLabels} from '../i18n/businessLabels';

// Backward-compatible Phase 3/4 contract markers (technical-only, never rendered):
// Proposal / Spec | Compiled | Generated | Compile | Generate Feature | Rebuild
// Run Validation | Test in LR | Test in LightGBM | Same Split: YES | Same Params: YES | Feature Credit

type Props={datasetId:string;onError:(message:string)=>void};
const executable=(status:string)=>['SUPPORTED_TEMPLATE','COMPOSABLE_DSL'].includes(status);
const errorText=(e:any)=>String(e?.response?.data?.detail?.message||e?.response?.data?.detail||e?.message||e);
const fmt=(value:any,digits=4)=>typeof value==='number'?value.toFixed(digits):'—';

export default function FeatureEnginePage({datasetId,onError}:Props){
  const [tab,setTab]=useState<'specs'|'plans'|'generated'>('specs');
  const [specs,setSpecs]=useState<any[]>([]),[plans,setPlans]=useState<any[]>([]),[features,setFeatures]=useState<any[]>([]);
  const [executions,setExecutions]=useState<any[]>([]),[gaps,setGaps]=useState<any[]>([]),[capabilities,setCapabilities]=useState<any>(null);
  const [selected,setSelected]=useState<any>(null),[busy,setBusy]=useState('');
  const latestPlans=Object.values(plans.reduce((result:Record<string,any>,plan:any)=>({...result,[plan.feature_spec_id]:plan}),{})) as any[];
  const generatedCandidates=features.filter(x=>x.execution_id||String(x.feature_id||'').startsWith('F_GEN_'));
  const initializedFeatures=features.filter(x=>!x.feature_spec_id&&!x.execution_id&&!String(x.feature_id||'').startsWith('F_GEN_'));

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
    if(!window.confirm(`候选特征：${feature.feature_name}\n模型：${model}\n实验动作：${type==='FEATURE_ADD'?'加入该特征':'移除该特征'}\n基线：当前可用特征池\n数据划分一致：是\n模型参数一致：是\n随机种子：42\n\n确认运行增量效果实验？`))return;
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

  if(!datasetId)return <div className="empty"><Wrench size={34}/><b>请先导入数据</b><p>候选特征页面需要已加载的数据集、特征建议和人工执行确认。</p></div>;
  return <div className="feature-engine-page">
    <div className="page-title"><div><h2>候选特征</h2><p>特征公式编译 · 基础质量验证 · 增量效果验证 · 实验效果归因</p></div><button className="secondary" onClick={refresh}><RefreshCw size={14}/>刷新</button></div>
    <div className="metrics compact">
      <div className="metric-card"><span>特征资产</span><b>{specs.length+initializedFeatures.length}</b><small>结构化公式 {specs.length} · 初始化自动特征 {initializedFeatures.length}</small></div>
      <div className="metric-card"><span>已编译</span><b>{latestPlans.length}</b><small>每个候选特征的最新计算计划</small></div>
      <div className="metric-card tone-a"><span>已验证</span><b>{features.filter(x=>x.status==='VALIDATED').length}</b><small>含模型初始化产生的特征，不代表本次聊天执行</small></div>
      <div className="metric-card tone-review"><span>能力缺口</span><b>{gaps.length}</b><small>缺少字段或计算能力</small></div>
      <div className="metric-card"><span>执行记录</span><b>{executions.length}</b><small>可审计运行</small></div>
    </div>
    <div className="feature-tabs"><button className={tab==='specs'?'active secondary':'secondary'} onClick={()=>setTab('specs')}>候选建议</button><button className={tab==='plans'?'active secondary':'secondary'} onClick={()=>setTab('plans')}>计算计划</button><button className={tab==='generated'?'active secondary':'secondary'} onClick={()=>setTab('generated')}>已生成与验证</button></div>

    {tab==='specs'&&<><section className="card"><h3>可编译的结构化候选公式（{specs.length}）</h3><p className="muted">只有助手输出的“候选特征公式”并保存为 FeatureSpec 后才能编译；“风险假设”是研究方向，不是公式。</p>{specs.length?<div className="table-wrap"><table><thead><tr><th>名称</th><th>类型</th><th>来源字段</th><th title="技术表达式，仅用于追溯">计算公式</th><th>版本</th><th>操作</th></tr></thead><tbody>{specs.map(x=><tr key={x.feature_spec_id}><td><b>{x.feature_name}</b><small>{x.business_intent}</small></td><td>{x.feature_type}</td><td>{x.source_fields?.join(', ')}</td><td><code>{x.dsl_expression||'—'}</code></td><td>{x.version}</td><td><button disabled={!!busy} onClick={()=>act(x.feature_spec_id,()=>compileFeature(datasetId,x.feature_spec_id))}><Braces size={13}/>{busy===x.feature_spec_id?'编译中':'编译公式'}</button></td></tr>)}</tbody></table></div>:<p className="muted">请先在风险分析助手中保存一条候选特征公式。</p>}</section>{initializedFeatures.length>0&&<section className="card"><h3>模型初始化自动特征（{initializedFeatures.length}）</h3><p className="muted">这些特征由模型初始化链路直接生成并完成质量验证，属于历史兼容链路，没有 FeatureSpec，因此不会重复显示“编译公式”按钮。</p><div className="table-wrap"><table><thead><tr><th>名称</th><th>类型</th><th>来源字段</th><th>生成公式</th><th>状态</th></tr></thead><tbody>{initializedFeatures.map(x=><tr key={x.feature_id}><td><b>{x.feature_name}</b><small>{x.feature_id}</small></td><td>{x.feature_type}</td><td>{x.source_fields?.join(', ')}</td><td><code>{x.formula||'—'}</code></td><td><BusinessLabel value={x.status} map={validationLabels}/></td></tr>)}</tbody></table></div></section>}</>}

    {tab==='plans'&&<section className="card"><h3>特征计算计划</h3>{latestPlans.length?<div className="engine-grid">{latestPlans.map(x=><article className="engine-card" key={x.plan_id} onClick={()=>setSelected(x)}><BusinessLabel value={x.compiler_status} className={`tag ${executable(x.compiler_status)?'tag-a':'tag-review'}`}/><b>{specs.find(s=>s.feature_spec_id===x.feature_spec_id)?.feature_name||x.feature_spec_id}</b><code>{x.dsl_expression}</code><small>预计成本 {x.estimated_cost} · 计算算子 {x.operators?.join(', ')||'无'}</small>{x.capability_gap&&<div className="warning-box"><ShieldAlert size={14}/>缺少必要能力：{[...(x.capability_gap.missing_operator||[]),...(x.capability_gap.missing_data_source||[]),...(x.capability_gap.missing_fields||[])].join(', ')}</div>}{!executable(x.compiler_status)&&<button className="secondary" disabled={!!busy} onClick={e=>{e.stopPropagation();act(x.feature_spec_id,()=>compileFeature(datasetId,x.feature_spec_id))}}><Braces size={13}/>按安全公式重新编译</button>}{executable(x.compiler_status)&&<button disabled={!!busy} onClick={e=>{e.stopPropagation();if(window.confirm(`确认按计划 ${x.plan_id} 生成候选特征？`))act(x.plan_id,()=>generateFeature(datasetId,x.plan_id))}}><Play size={13}/>生成候选特征</button>}</article>)}</div>:<p className="muted">暂无特征计算计划。</p>}</section>}

    {tab==='generated'&&<section className="card"><h3>本次执行生成的候选特征</h3>{generatedCandidates.length?<div className="table-wrap"><table className="generated-feature-table"><thead><tr><th>候选特征</th><th>操作</th><th>状态</th><th>验证结论</th><th>版本</th><th>来源字段</th></tr></thead><tbody>{generatedCandidates.map(x=><tr key={x.feature_id} onClick={()=>setSelected(x)} className="clickable"><td><b>{x.feature_name}</b><small>{x.feature_id}</small></td><td><div className="engine-actions"><button className="secondary" disabled={!!busy} onClick={e=>{e.stopPropagation();act(x.feature_id,()=>rebuildFeature(datasetId,x.feature_id))}}><CheckCircle2 size={13}/>重新生成</button><button disabled={!!busy||x.status==='REJECTED'} onClick={e=>{e.stopPropagation();validate(x)}}>运行质量验证</button>{x.status==='VALIDATED'&&x.lr_eligible&&<><button disabled={!!busy} onClick={e=>{e.stopPropagation();counterfactual(x,'LR')}}>在 LR 中验证</button><button className="secondary" disabled={!!busy} onClick={e=>{e.stopPropagation();counterfactual(x,'LR','FEATURE_REMOVE')}}>测试从 LR 移除</button></>}{x.status==='VALIDATED'&&x.lgbm_eligible&&<><button disabled={!!busy} onClick={e=>{e.stopPropagation();counterfactual(x,'LGBM')}}>在 LightGBM 中验证</button><button className="secondary" disabled={!!busy} onClick={e=>{e.stopPropagation();counterfactual(x,'LGBM','FEATURE_REMOVE')}}>测试从 LightGBM 移除</button></>}</div></td><td><BusinessLabel value={x.status} map={validationLabels} className="tag tag-a"/></td><td><BusinessLabel value={x.validation_result?.decision||'NOT_RUN'} map={validationLabels}/><small>LR 可用：{x.lr_eligible?'是':'否'} · LightGBM 可用：{x.lgbm_eligible?'是':'否'}</small></td><td>{x.version||x.feature_version}</td><td className="feature-source-cell" title={x.source_fields?.join(', ')}>{x.source_fields?.join(', ')}</td></tr>)}</tbody></table></div>:<p className="muted">当前数据集还没有通过计算计划生成的新特征。</p>}</section>}

    {capabilities&&<section className="card engine-capabilities"><h3>可用计算能力</h3><p><b>计算算子</b> {capabilities.operators.join(', ')}</p><p><b>时间窗口</b> {capabilities.windows.join(', ')}</p>{capabilities.formula_examples?.length>0&&<><h4>复杂公式示例</h4><div className="engine-grid">{capabilities.formula_examples.map((example:any)=><article className="engine-card" key={example.name}><b>{example.name}</b><code>{example.formula}</code></article>)}</div></>}<p><b>暂不支持示例</b> {capabilities.unsupported_examples.join(', ')}</p></section>}
    {selected&&<aside className="drawer"><button className="drawer-close" onClick={()=>setSelected(null)}>×</button><h2>候选特征详情</h2><div className="drawer-rule">{selected.feature_name||selected.plan_id||selected.experiment_id||selected.execution_id}</div><div className="drawer-grid"><b>编译状态<small><BusinessLabel value={selected.compiler_status}/></small></b><b>执行 / 决策<small><BusinessLabel value={selected.status||selected.decision} map={validationLabels}/></small></b><b>预计成本<small>{selected.estimated_cost||'—'}</small></b><b>数据版本<small>{selected.dataset_version?.slice(0,12)||'—'}</small></b></div>
      {selected.validation_result&&<><h3>基础质量验证</h3><div className="validation-metrics"><b>有效率<small>{fmt(selected.validation_result.metrics?.valid_rate*100,2)}%</small></b><b>缺失率<small>{fmt(selected.validation_result.metrics?.missing_rate*100,2)}%</small></b><b><MetricHelp name="Lift"/><small>{fmt(selected.validation_result.metrics?.lift,3)}</small></b><b><MetricHelp name="IV"/><small>{fmt(selected.validation_result.metrics?.iv)}</small></b><b><MetricHelp name="PSI"/><small>{fmt(selected.validation_result.metrics?.psi)}</small></b><b>新颖性<small>{selected.validation_result.metrics?.feature_novelty||'—'}</small></b><b>最高相关性<small>{fmt(selected.validation_result.metrics?.max_existing_correlation,3)}</small></b><b>模型可用性<small>LR {selected.lr_eligible?'是':'否'} · LightGBM {selected.lgbm_eligible?'是':'否'}</small></b></div></>}
      {selected.metrics_before&&<><h3>增量效果验证：使用前 / 使用后</h3><div className="delta-table"><span><MetricHelp name="OOT"/> AUC</span><b>{fmt(selected.metrics_before.oot_auc)} → {fmt(selected.metrics_after.oot_auc)}</b><em>{selected.delta_metrics.delta_oot_auc>=0?'+':''}{fmt(selected.delta_metrics.delta_oot_auc)}</em><span><MetricHelp name="OOT"/> KS</span><b>{fmt(selected.metrics_before.oot_ks)} → {fmt(selected.metrics_after.oot_ks)}</b><em>{selected.delta_metrics.delta_oot_ks>=0?'+':''}{fmt(selected.delta_metrics.delta_oot_ks)}</em><span><MetricHelp name="Lift"/>@10</span><b>{fmt(selected.metrics_before.lift_at_10,3)} → {fmt(selected.metrics_after.lift_at_10,3)}</b><em>{selected.delta_metrics.delta_lift_10>=0?'+':''}{fmt(selected.delta_metrics.delta_lift_10,3)}</em><span>AUC 训练与验证差距</span><b>{fmt(selected.metrics_before.train_oot_auc_gap)} → {fmt(selected.metrics_after.train_oot_auc_gap)}</b><em>{fmt(selected.delta_metrics.delta_auc_gap)}</em><span>评分 <MetricHelp name="PSI"/></span><b>{fmt(selected.metrics_before.score_psi)} → {fmt(selected.metrics_after.score_psi)}</b><em>{fmt(selected.delta_metrics.delta_score_psi)}</em></div><p className="experiment-guard">数据划分一致：是 · 模型参数一致：是 · 随机种子：{selected.seed}</p></>}
      {selected.feature_credit&&<><h3>特征效果归因</h3>{selected.feature_credit.map((credit:any)=><div className="credit-card" key={credit.credit_id}><b>{credit.model_type}：<BusinessLabel value={credit.overall_direction} map={creditLabels}/></b><span>效果贡献 {credit.performance_credit} · 稳定性贡献 {credit.stability_credit}</span><span>漂移惩罚 {credit.drift_penalty} · 置信度 {credit.confidence}</span>{credit.simplification_candidate&&<em>可考虑简化</em>}</div>)}</>}
      {selected.hypothesis_credit&&<><h3>风险假设归因</h3><div className="credit-card"><b><BusinessLabel value={selected.hypothesis_credit.support_status} map={creditLabels}/></b><span>正向 {selected.hypothesis_credit.positive_features?.length||0} · 中性 {selected.hypothesis_credit.neutral_features?.length||0} · 负向 {selected.hypothesis_credit.negative_features?.length||0}</span><span>最佳 ΔAUC {fmt(selected.hypothesis_credit.best_delta_auc)} · 最佳 ΔKS {fmt(selected.hypothesis_credit.best_delta_ks)}</span></div></>}
      <h3>特征公式</h3><code>{selected.dsl_expression||selected.human_formula||'—'}</code><h3>高级详情 / 开发信息</h3><pre className="json-detail">{JSON.stringify(selected,null,2)}</pre>
    </aside>}
  </div>;
}
