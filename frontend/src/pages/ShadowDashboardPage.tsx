import {useEffect,useState} from 'react';
import {RefreshCw} from 'lucide-react';
import {getShadowErrors,getShadowPredictions,getShadowStatus,retrainShadow} from '../api/client';
import {BusinessLabel} from '../components/BusinessLabel';
import {actionLabels,creditLabels,surrogateLabels} from '../i18n/businessLabels';
import '../shadow.css';

type Props={datasetId:string;onError:(message:string)=>void};
const value=(x:any,digits=3)=>x==null?'—':Number(x).toFixed(digits);

export default function ShadowDashboardPage({datasetId,onError}:Props){
  const [status,setStatus]=useState<any>(null),[rows,setRows]=useState<any[]>([]),[errors,setErrors]=useState<any[]>([]),[busy,setBusy]=useState(false);
  const load=async()=>{if(!datasetId)return;setBusy(true);try{const [s,p,e]=await Promise.all([getShadowStatus(datasetId),getShadowPredictions(datasetId),getShadowErrors(datasetId)]);setStatus(s.data);setRows(p.data);setErrors(e.data.items||[])}catch(err:any){onError(err?.response?.data?.detail||err?.message||'历史实验预测页面加载失败')}finally{setBusy(false)}};
  useEffect(()=>{load()},[datasetId]);
  if(!datasetId)return <div className="page"><section className="card"><h2>历史实验预测</h2><p className="muted">请先导入数据并运行真实模型实验。</p></section></div>;
  const metrics=status?.evaluation?.windows?.ALL_HISTORY||{},cl=metrics.classification||{},reg=metrics.regression||{},rank=metrics.ranking||{};
  const retrain=async()=>{setBusy(true);try{await retrainShadow(datasetId);await load()}catch(err:any){onError(err?.response?.data?.detail||err?.message)}finally{setBusy(false)}};
  return <div className="page shadow-page">
    <div className="page-title"><div><h2>历史实验预测</h2><p>只作辅助预测；最终执行选择始终由既有系统规则控制。</p></div><button disabled={busy} onClick={retrain}><RefreshCw size={15}/>人工重新训练</button></div>
    <div className="shadow-banner"><b><BusinessLabel value="SHADOW_ONLY" map={surrogateLabels}/></b><span>不用于替代最终决策</span><span>当前仍按系统规则执行</span></div>
    <div className="shadow-kpis">{[['可用真实实验',status?.real_usable],['下一检查点',status?.next_checkpoint||'门槛复核'],['真实预测数',status?.real_predictions],['已有真实结果',status?.actual_available],['正向比例',value(cl.positive_rate)],['AUC',value(cl.auc)],['ΔAUC 排序相关性',value(reg.spearman)],['NDCG@10',value(rank.shadow_ndcg_at_10)],['Brier 误差',value(cl.brier_score)],['校准误差 ECE',value(cl.ece)],['历史差异率',value(metrics.ood_rate)]].map(([k,v])=><span key={String(k)}><small>{k}</small><b>{v??'—'}</b></span>)}</div>
    {status?.evaluation?.performance_drift&&<div className="warning-box" title="技术原值：SURROGATE_PERFORMANCE_DRIFT">预测表现发生漂移，当前继续保持旁路观察，不参与最终排序。</div>}
    <section className="card"><h3>辅助预测与真实结果对照</h3><div className="shadow-table-wrap"><table className="shadow-table"><thead><tr><th>候选项</th><th>系统当前排序</th><th>历史预测排序</th><th>预计有效概率</th><th>预计 ΔAUC</th><th>真实结果</th><th>真实 ΔAUC</th><th>预测误差</th><th>状态</th></tr></thead><tbody>{[...rows].reverse().map(x=><tr key={x.shadow_id}><td>{x.candidate_id}</td><td>第 {x.phase5_rank} 名</td><td>{x.shadow_rank?`第 ${x.shadow_rank} 名`:'—'}</td><td>{x.positive_probability==null?'—':`${(x.positive_probability*100).toFixed(1)}%`}</td><td>{value(x.expected_delta_auc,4)}</td><td><BusinessLabel value={x.actual_decision} map={creditLabels}/></td><td>{value(x.actual_delta_auc,4)}</td><td>{x.actual_delta_auc==null?'—':value(Math.abs(Number(x.actual_delta_auc)-Number(x.expected_delta_auc||0)),4)}</td><td><BusinessLabel value={x.status} map={surrogateLabels} className="shadow-only"/></td></tr>)}</tbody></table></div></section>
    <section className="card"><h3>预测误差最大的 10 条记录</h3><div className="shadow-table-wrap"><table className="shadow-table"><thead><tr><th>候选项</th><th>分类是否错误</th><th>方向是否错误</th><th>ΔAUC 绝对误差</th><th>业务领域</th><th>实验动作</th></tr></thead><tbody>{errors.slice(0,10).map(x=>{const row=rows.find(r=>r.shadow_id===x.shadow_id)||{};return <tr key={x.error_id}><td>{row.candidate_id||x.shadow_id}</td><td>{x.classification_error?'是':'否'}</td><td>{x.direction_error?'是':'否'}</td><td>{value(x.absolute_error?.auc,4)}</td><td>{x.semantic_domain}</td><td><BusinessLabel value={x.action_type} map={actionLabels}/></td></tr>})}</tbody></table></div></section>
  </div>
}
