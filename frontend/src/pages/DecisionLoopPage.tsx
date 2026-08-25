import {useState} from 'react';
import {Check,FastForward,GitBranch,Play,RotateCcw,Square,X} from 'lucide-react';
import {approveDecision,createDecisionLoop,executeDecisionPlan,getDecisionLoop,nextDecisionRound,rejectDecision,rollbackDecision,stopDecisionLoop} from '../api/client';
import {BusinessLabel} from '../components/BusinessLabel';
import {actionLabels,creditLabels,diagnosisLabels,surrogateLabels} from '../i18n/businessLabels';

type Props={datasetId:string;onError:(message:string)=>void};
const msg=(e:any)=>e?.response?.data?.detail||e?.message||'实验决策操作失败';

export default function DecisionLoopPage({datasetId,onError}:Props){
  const [loopId,setLoopId]=useState(''),[data,setData]=useState<any>(null),[busy,setBusy]=useState(''),[useLlm,setUseLlm]=useState(false);
  const refresh=async(id=loopId)=>{if(!id)return;const r=await getDecisionLoop(datasetId,id);setData(r.data)};
  const act=async(label:string,fn:()=>Promise<any>)=>{setBusy(label);onError('');try{const r=await fn();const id=r.data.loop_id||loopId;if(id&&!loopId)setLoopId(id);await refresh(id)}catch(e){onError(msg(e))}finally{setBusy('')}};
  const create=()=>act('create',async()=>{const r=await createDecisionLoop(datasetId);setLoopId(r.data.loop_id);return r});
  if(!datasetId)return <div className="page"><section className="card"><h2>实验决策助手</h2><p className="muted">请先导入数据并完成模型与特征实验。</p></section></div>;
  const loop=data?.loop||{},decision=data?.decisions?.at(-1),plan=data?.plans?.at(-1),feedback=data?.feedback||{};
  const shadowOrder=[...(decision?.candidate_actions||[])].filter((x:any)=>x.positive_probability!=null).sort((a:any,b:any)=>Number(b.positive_probability)-Number(a.positive_probability));
  return <div className="page decision-page">
    <div className="page-title"><div><h2>实验决策助手</h2><p>每次只规划并执行一个主要变化因素，不会自动无限循环，也不会自动上线。</p></div><div className="agent-actions">
      {!loopId&&<button disabled={!!busy} onClick={create}><GitBranch size={15}/>创建决策流程</button>}
      <label className="decision-toggle" title="使用已配置的大模型辅助解释决策；真实计算仍由 Python 完成"><input type="checkbox" checked={useLlm} onChange={e=>setUseLlm(e.target.checked)}/>使用 LLM 辅助决策</label>
      <button disabled={!!busy||!loopId||loop.status==='WAITING_APPROVAL'} onClick={()=>act('next',()=>nextDecisionRound(datasetId,loopId,useLlm))}><FastForward size={15}/>开始下一轮决策</button>
      <button disabled={!!busy||!plan||loop.status!=='RUNNING'} onClick={()=>act('execute',()=>executeDecisionPlan(datasetId,loopId))}><Play size={15}/>运行选定实验</button>
      <button disabled={!!busy||loop.status!=='WAITING_APPROVAL'} onClick={()=>act('approve',()=>approveDecision(datasetId,loopId))}><Check size={15}/>同意并继续</button>
      <button className="danger-button" disabled={!!busy||loop.status!=='WAITING_APPROVAL'} onClick={()=>act('reject',()=>rejectDecision(datasetId,loopId))}><X size={15}/>拒绝</button>
      <button className="secondary" disabled={!!busy||!loopId} onClick={()=>act('rollback',()=>rollbackDecision(datasetId,loopId))}><RotateCcw size={15}/>回退版本</button>
      <button className="danger-button" disabled={!!busy||!loopId} onClick={()=>act('stop',()=>stopDecisionLoop(datasetId,loopId))}><Square size={14}/>停止流程</button>
    </div></div>
    {!loopId?<section className="card"><h3>受控决策流程</h3><p className="muted">创建流程后，系统先诊断并生成计划，再由用户明确运行实验。</p></section>:<>
      <div className="decision-state"><span><small>当前状态</small><b><BusinessLabel value={loop.status}/></b></span><span><small>当前轮次</small><b>{loop.round} / {loop.budget?.max_rounds}</b></span><span><small>剩余额度</small><b>{loop.budget_remaining} 次实验</b></span><span><small>当前版本</small><b>{loop.current_state_id||'—'}</b></span><span><small>当前最佳版本</small><b>{loop.best_state_id||'—'}</b></span><span><small>最近稳定版本</small><b>{loop.last_stable_state_id||'—'}</b></span></div>
      {decision&&<section className="card decision-summary"><h3>决策摘要</h3><div className="decision-grid"><div><small>问题诊断</small><b><BusinessLabel value={decision.diagnosis} map={diagnosisLabels}/></b><em>置信度 {decision.diagnosis_confidence}</em></div><div><small>建议动作</small><b><BusinessLabel value={decision.selected_action?.action_type} map={actionLabels}/></b><em>{decision.selected_action?.reason}</em></div><div><small>预期影响</small><b>{decision.expected_effect}</b><em>风险等级 <BusinessLabel value={decision.risk_level}/></em></div><div><small>人工审批</small><b>{decision.requires_human_approval?'需要人工确认':'无需人工确认'}</b><em>{loop.pending_approval_id||'—'}</em></div></div>
        <h4>判断证据</h4><div className="evidence-list">{decision.evidence?.map((x:any,i:number)=><div key={i}><b title={`技术原因代码：${x.reason_code}`}>证据 {i+1}</b><small>{x.source_id}</small><code>{JSON.stringify(x.facts)}</code></div>)}</div>
        <h4>候选动作</h4><div className="candidate-list">{decision.candidate_actions?.map((x:any,i:number)=><span className={x.action_type===decision.selected_action?.action_type?'selected':''} key={i}><b><BusinessLabel value={x.action_type} map={actionLabels}/></b><small>系统当前排序：第 {i+1} 名 · 当前仍按系统规则执行</small><small>历史实验预测：{x.positive_probability!=null?`第 ${shadowOrder.indexOf(x)+1} 名 · 预计有效概率 ${(x.positive_probability*100).toFixed(1)}%`:'预测未启用'}</small><small><BusinessLabel value={x.ranking_mode||'PHASE5_FALLBACK'} map={surrogateLabels}/> · 成本 {x.cost} · 风险 <BusinessLabel value={x.risk}/></small>{x.ranking_mode==='PHASE5_FALLBACK'&&<small>历史实验预测未参与最终排序</small>}{x.positive_probability!=null&&<small>辅助预测：ΔAUC {Number(x.expected_delta_auc||0).toFixed(4)} · 不确定性 <BusinessLabel value={x.uncertainty}/></small>}{x.surrogate_prediction?.out_of_distribution&&<small>⚠ 与历史实验差异较大：距离 {Number(x.surrogate_prediction.nearest_experiment_distance||0).toFixed(2)}，预测不确定性高</small>}{x.similar_experiments?.length>0&&<small>相似历史实验：{x.similar_experiments.length} 条（仅参考）</small>}</span>)}</div>
      </section>}
      {plan&&<section className="card"><h3>实验计划</h3><div className="plan-row"><b><BusinessLabel value={plan.action_type} map={actionLabels}/></b><span>候选特征：{plan.feature_ids?.join(', ')||'—'}</span><span>模型：{plan.model_type||'—'}</span><span>执行工具：{plan.required_tools?.join(', ')||'暂无可用执行工具'}</span><span>单一变化因素：是</span></div></section>}
      <section className="card"><h3>实验时间线</h3><div className="timeline">{loop.tested_actions?.length?loop.tested_actions.map((x:any)=><div key={x.plan_id}><i/><span><small>第 {x.round} 轮</small><b><BusinessLabel value={x.action_type} map={actionLabels}/> {x.feature_ids?.join(', ')}</b><em>真实结果：<BusinessLabel value={x.outcome} map={creditLabels}/></em>{x.prediction?.positive_probability!=null&&<small>辅助预测：有效概率 {(x.prediction.positive_probability*100).toFixed(1)}% · 预计 ΔAUC {Number(x.prediction.expected_delta_auc||0).toFixed(4)}</small>}{x.actual_delta_metrics?.delta_oot_auc!=null&&<small>真实 ΔAUC {Number(x.actual_delta_metrics.delta_oot_auc).toFixed(4)} · 预测误差 {(Number(x.actual_delta_metrics.delta_oot_auc)-Number(x.prediction?.expected_delta_auc||0)).toFixed(4)}</small>}</span></div>):<p className="muted">暂无实验反馈。</p>}</div>{feedback.stop_reason&&<div className="warning-box" title={`技术原值：${feedback.stop_reason}`}>停止原因：流程已达到停止条件，请查看审计详情。</div>}</section>
    </>}
  </div>
}
