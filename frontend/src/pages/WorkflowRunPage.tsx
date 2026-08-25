import {useEffect,useState} from 'react';
import {Check,Play,RefreshCw,RotateCcw,Square,X} from 'lucide-react';
import {approveWorkflow,cancelWorkflow,getWorkflowRun,getWorkflowTimeline,rejectWorkflow,retryWorkflowNode,rollbackWorkflow,startWorkflow,workflowDefinition} from '../api/client';
import {BusinessLabel} from '../components/BusinessLabel';
import '../workflow.css';

type Props={datasetId:string;onError:(message:string)=>void};
const entries=['RUN_ALL','FROM_ANALYSIS','FROM_FEATURE','FROM_VALIDATION','FROM_DECISION','FROM_EXPERIMENT'];
const entryLabels:Record<string,string>={RUN_ALL:'运行完整流程',FROM_ANALYSIS:'从风险分析开始',FROM_FEATURE:'从候选特征开始',FROM_VALIDATION:'从质量验证开始',FROM_DECISION:'从实验决策开始',FROM_EXPERIMENT:'从模型实验开始'};
const nodeLabels:Record<string,string>={load_context:'加载分析上下文',analysis_agent:'风险分析助手',proposal_validation:'校验分析建议',human_proposal_approval:'人工确认建议',feature_compile:'编译特征公式',feature_generate:'生成候选特征',cheap_validation:'基础质量验证',feature_counterfactual:'增量效果验证',credit_assignment:'归因实验效果',model_evaluation:'评估模型状态',decision_agent:'实验决策助手',human_experiment_approval:'人工确认实验',experiment_execute:'执行模型实验',feedback_record:'记录实验反馈',surrogate_shadow:'历史实验预测',rollback:'回退稳定版本',finalize:'完成流程'};

export default function WorkflowRunPage({datasetId,onError}:Props){
  const [entry,setEntry]=useState('RUN_ALL'),[feature,setFeature]=useState(''),[runId,setRunId]=useState(''),[data,setData]=useState<any>(null),[timeline,setTimeline]=useState<any[]>([]),[definition,setDefinition]=useState<any>({nodes:[]}),[busy,setBusy]=useState('');
  useEffect(()=>{workflowDefinition().then(r=>setDefinition(r.data)).catch(()=>{})},[]);
  const load=async(id=runId)=>{if(!id)return;const [r,t]=await Promise.all([getWorkflowRun(id),getWorkflowTimeline(id)]);setData(r.data);setTimeline(t.data.items||[])};
  const act=async(label:string,fn:()=>Promise<any>)=>{setBusy(label);onError('');try{const response=await fn();const id=response.data?.run?.run_id||runId;if(id)setRunId(id);if(id)await load(id)}catch(e:any){onError(e?.response?.data?.detail||e?.message||'工作流操作失败')}finally{setBusy('')}};
  const start=()=>act('start',()=>startWorkflow({dataset_id:datasetId,segment:'NEW',entry_point:entry,selected_feature_id:feature||undefined}));
  if(!datasetId)return <div className="page"><section className="card"><h2>风险研究工作流</h2><p className="muted">请先导入数据，再启动可审计、可暂停和可恢复的分析工作流。</p></section></div>;
  const run=data?.run||{},state=data?.state||{},failed=run.status==='FAILED',waiting=run.status==='WAITING';
  return <div className="page workflow-page">
    <div className="page-title"><div><h2>风险研究工作流</h2><p>自动串联已有分析步骤；流程断点与业务版本回退相互独立。</p></div><div className="workflow-controls"><select aria-label="工作流起点" value={entry} onChange={e=>setEntry(e.target.value)}>{entries.map(x=><option key={x} value={x}>{entryLabels[x]}</option>)}</select><input aria-label="候选特征编号" placeholder="候选特征编号（可选）" value={feature} onChange={e=>setFeature(e.target.value)}/><button disabled={!!busy} onClick={start}><Play size={15}/>启动工作流</button></div></div>
    {runId&&<><div className="workflow-state"><span><small>当前状态</small><b><BusinessLabel value={run.status}/></b></span><span><small>当前步骤</small><b title={`技术原值：${run.current_node||''}`}>{nodeLabels[run.current_node]||run.current_node||'—'}</b></span><span><small>决策轮次</small><b>{state.decision_round??0} / 3</b></span><span><small>剩余实验额度</small><b>{state.budget_remaining??6} / 6</b></span><span><small>业务版本</small><b>{state.current_business_state_id||'—'}</b></span><span><small>流程断点</small><b>{run.checkpoint_id?.slice(0,12)||'—'}</b></span></div>
      <section className="card"><div className="workflow-actions"><h3>流程步骤</h3>{waiting&&<><button onClick={()=>act('approve',()=>approveWorkflow(runId))}><Check size={14}/>同意并继续</button><button className="danger-button" onClick={()=>act('reject',()=>rejectWorkflow(runId))}><X size={14}/>拒绝</button></>}{failed&&<><button onClick={()=>act('retry',()=>retryWorkflowNode(runId,run.current_node))}><RefreshCw size={14}/>重新尝试</button><button className="secondary" onClick={()=>act('rollback',()=>rollbackWorkflow(runId))}><RotateCcw size={14}/>回退版本</button></>}<button className="danger-button" disabled={['SUCCESS','CANCELLED'].includes(run.status)} onClick={()=>act('cancel',()=>cancelWorkflow(runId))}><Square size={14}/>停止流程</button></div><div className="workflow-nodes">{definition.nodes?.map((node:string)=><span key={node} className={`${state.node_status?.[node]||'NOT_STARTED'} ${run.current_node===node?'current':''}`} title={`技术节点：${node}`}><b>{nodeLabels[node]||node}</b><BusinessLabel value={state.node_status?.[node]||'NOT_STARTED'}/></span>)}</div></section>
      <section className="card"><h3>审计时间线</h3><div className="workflow-timeline">{timeline.length?timeline.map(x=><div key={x.node_run_id}><i className={x.status}/><span><small>{x.started_at}</small><b title={`技术节点：${x.node}`}>{nodeLabels[x.node]||x.node}</b><em><BusinessLabel value={x.status}/> · {Number(x.duration_ms||0).toFixed(2)} 毫秒</em>{x.error&&<code title={`技术错误：${x.error.type}`}>执行失败：{x.error.summary}</code>}{x.reason_codes?.length>0&&<small>原因代码：{x.reason_codes.join(', ')}</small>}<small>结果引用：{JSON.stringify(x.output_refs||{})}</small></span></div>):<p className="muted">暂无工作流执行记录。</p>}</div></section>
      {state.errors?.length>0&&<section className="card workflow-errors"><h3>失败信息</h3>{state.errors.map((x:any,i:number)=><div key={i}><b title={`技术原值：${x.type}`}>工作流执行失败</b><span>{x.summary}</span></div>)}</section>}
    </>}
  </div>
}
