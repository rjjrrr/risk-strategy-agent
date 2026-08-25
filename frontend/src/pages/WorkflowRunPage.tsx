import {useEffect,useState} from 'react';
import {Check,ChevronRight,Play,RefreshCw,RotateCcw,Square,X} from 'lucide-react';
import {approveWorkflow,cancelWorkflow,getWorkflowRun,getWorkflowTimeline,rejectWorkflow,retryWorkflowNode,rollbackWorkflow,startWorkflow,workflowDefinition} from '../api/client';
import {BusinessLabel} from '../components/BusinessLabel';
import '../workflow.css';

type Props={datasetId:string;onError:(message:string)=>void};
const entryLabels:Record<string,string>={RUN_ALL:'运行完整流程',FROM_ANALYSIS:'从风险分析开始',FROM_FEATURE:'从候选特征开始',FROM_VALIDATION:'从质量验证开始',FROM_DECISION:'从实验决策开始',FROM_EXPERIMENT:'从模型实验开始'};
const startStages=[
  {entry:'RUN_ALL',label:'风险分析',description:'读取上下文并生成建议'},
  {entry:'FROM_FEATURE',label:'候选特征',description:'编译并生成安全公式'},
  {entry:'FROM_VALIDATION',label:'质量验证',description:'基础质量与稳定性检查'},
  {entry:'FROM_DECISION',label:'实验决策',description:'选择下一项真实实验'},
  {entry:'FROM_EXPERIMENT',label:'模型实验',description:'反事实评估与效果归因'},
];
const nodeLabels:Record<string,string>={entry_router:'选择流程入口',build_context:'加载分析上下文',analysis:'风险分析助手',proposal_guard:'校验分析建议',human_review_proposal:'人工确认建议',feature_compile:'编译特征公式',feature_review:'人工复核特征',feature_execute:'生成候选特征',cheap_validation:'基础质量验证',decision_context:'加载实验上下文',decision:'实验决策助手',experiment_plan:'生成实验计划',shadow_predict:'历史实验旁路预测',approval_gate:'人工确认实验',experiment_execute:'执行模型实验',counterfactual_evaluate:'反事实增量验证',credit_update:'归因实验效果',shadow_reconcile:'记录预测误差',next_decision:'判断是否继续',rollback_node:'回退稳定版本'};

export default function WorkflowRunPage({datasetId,onError}:Props){
  const [entry,setEntry]=useState('RUN_ALL'),[feature,setFeature]=useState(''),[runId,setRunId]=useState(''),[data,setData]=useState<any>(null),[timeline,setTimeline]=useState<any[]>([]),[definition,setDefinition]=useState<any>({nodes:[]}),[busy,setBusy]=useState('');
  useEffect(()=>{workflowDefinition().then(r=>setDefinition(r.data)).catch(()=>{})},[]);
  const load=async(id=runId)=>{if(!id)return;const [r,t]=await Promise.all([getWorkflowRun(id),getWorkflowTimeline(id)]);setData(r.data);setTimeline(t.data.items||[])};
  const act=async(label:string,fn:()=>Promise<any>)=>{setBusy(label);onError('');try{const response=await fn();const id=response.data?.run?.run_id||runId;if(id)setRunId(id);if(id)await load(id)}catch(e:any){onError(e?.response?.data?.detail||e?.message||'工作流操作失败')}finally{setBusy('')}};
  const start=()=>act('start',()=>startWorkflow({dataset_id:datasetId,segment:'NEW',entry_point:entry,selected_feature_id:feature||undefined}));
  if(!datasetId)return <div className="page"><section className="card"><h2>风险研究工作流</h2><p className="muted">请先导入数据，再启动可审计、可暂停和可恢复的分析工作流。</p></section></div>;
  const run=data?.run||{},state=data?.state||{},failed=run.status==='FAILED',waiting=run.status==='WAITING';
  return <div className="page workflow-page">
    <div className="page-title"><div><h2>风险研究工作流</h2><p>点击流程节点选择起点，再启动可审计、可暂停和可恢复的研究流程。</p></div></div>
    <section className="card workflow-launcher">
      <div className="workflow-launcher-head"><div><h3>选择工作流起点</h3><p>当前选择：{entryLabels[entry]}</p></div><div className="workflow-controls"><input aria-label="候选特征编号" placeholder="候选特征编号（可选）" value={feature} onChange={e=>setFeature(e.target.value)}/><button disabled={!!busy} onClick={start}><Play size={15}/>{busy==='start'?'启动中':'启动工作流'}</button></div></div>
      <div className="workflow-start-path">{startStages.map((stage,index)=><div className="workflow-start-step" key={stage.entry}><button type="button" aria-pressed={entry===stage.entry} className={entry===stage.entry?'selected':''} onClick={()=>setEntry(stage.entry)}><span>{index+1}</span><b>{stage.label}</b><small>{stage.description}</small></button>{index<startStages.length-1&&<ChevronRight className="workflow-arrow" size={20}/>}</div>)}</div>
    </section>
    {runId&&<><div className="workflow-state"><span><small>当前状态</small><b><BusinessLabel value={run.status}/></b></span><span><small>当前步骤</small><b title={`技术原值：${run.current_node||''}`}>{nodeLabels[run.current_node]||run.current_node||'—'}</b></span><span><small>决策轮次</small><b>{state.decision_round??0} / 3</b></span><span><small>剩余实验额度</small><b>{state.budget_remaining??6} / 6</b></span><span><small>业务版本</small><b>{state.current_business_state_id||'—'}</b></span><span><small>流程断点</small><b>{run.checkpoint_id?.slice(0,12)||'—'}</b></span></div>
      <section className="card"><div className="workflow-actions"><h3>流程步骤</h3>{waiting&&<><button onClick={()=>act('approve',()=>approveWorkflow(runId))}><Check size={14}/>同意并继续</button><button className="danger-button" onClick={()=>act('reject',()=>rejectWorkflow(runId))}><X size={14}/>拒绝</button></>}{failed&&<><button onClick={()=>act('retry',()=>retryWorkflowNode(runId,run.current_node))}><RefreshCw size={14}/>重新尝试</button><button className="secondary" onClick={()=>act('rollback',()=>rollbackWorkflow(runId))}><RotateCcw size={14}/>回退版本</button></>}<button className="danger-button" disabled={['SUCCESS','CANCELLED'].includes(run.status)} onClick={()=>act('cancel',()=>cancelWorkflow(runId))}><Square size={14}/>停止流程</button></div><div className="workflow-nodes">{definition.nodes?.map((node:string)=><span key={node} className={`${state.node_status?.[node]||'NOT_STARTED'} ${run.current_node===node?'current':''}`} title={`技术节点：${node}`}><b>{nodeLabels[node]||node}</b><BusinessLabel value={state.node_status?.[node]||'NOT_STARTED'}/></span>)}</div></section>
      <section className="card"><h3>审计时间线</h3><div className="workflow-timeline">{timeline.length?timeline.map(x=><div key={x.node_run_id}><i className={x.status}/><span><small>{x.started_at}</small><b title={`技术节点：${x.node}`}>{nodeLabels[x.node]||x.node}</b><em><BusinessLabel value={x.status}/> · {Number(x.duration_ms||0).toFixed(2)} 毫秒</em>{x.error&&<code title={`技术错误：${x.error.type}`}>执行失败：{x.error.summary}</code>}{x.reason_codes?.length>0&&<small>原因代码：{x.reason_codes.join(', ')}</small>}<small>结果引用：{JSON.stringify(x.output_refs||{})}</small></span></div>):<p className="muted">暂无工作流执行记录。</p>}</div></section>
      {state.errors?.length>0&&<section className="card workflow-errors"><h3>失败信息</h3>{state.errors.map((x:any,i:number)=><div key={i}><b title={`技术原值：${x.type}`}>工作流执行失败</b><span>{x.summary}</span></div>)}</section>}
    </>}
  </div>
}
