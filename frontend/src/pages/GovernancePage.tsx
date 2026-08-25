import {useMemo,useState} from 'react';
import {Search} from 'lucide-react';
import {Metric,Empty} from '../components/Common';
import {BusinessLabel} from '../components/BusinessLabel';
import type {Governance} from '../types';

const decisions=['ALL','KEEP','EXCLUDE','SUSPECT_LEAKAGE','SPECIAL','IDENTIFIER','REVIEW'];
export default function GovernancePage({rows,onChange}:{rows:Governance[];onChange:(field:string,d:string)=>void}){
  const [q,setQ]=useState(''),[filter,setFilter]=useState('ALL');
  const view=useMemo(()=>rows.filter(x=>(filter==='ALL'||x.decision===filter)&&x.field.toLowerCase().includes(q.toLowerCase())),[rows,q,filter]);
  if(!rows.length)return <div className="page"><Empty title="尚未执行字段治理" text="请先从数据导入页开始字段治理"/></div>;
  return <div className="page"><div className="page-title"><div><h2>字段治理</h2><p>综合字段语义、质量和可用性给出建议；人工调整会记录到当前数据集。</p></div></div>
    <div className="metrics compact"><Metric label="字段总数" value={rows.length}/><Metric label="保留使用" value={rows.filter(x=>x.decision==='KEEP').length}/><Metric label="已排除" value={rows.filter(x=>x.decision==='EXCLUDE').length}/><Metric label="疑似泄漏" value={rows.filter(x=>x.decision==='SUSPECT_LEAKAGE').length}/><Metric label="标识字段" value={rows.filter(x=>x.semantic_type==='IDENTIFIER').length}/></div>
    <div className="toolbar"><span className="search"><Search size={15}/><input placeholder="搜索字段" value={q} onChange={e=>setQ(e.target.value)}/></span><select aria-label="治理结论筛选" value={filter} onChange={e=>setFilter(e.target.value)}>{decisions.slice(0,5).map(x=><option value={x} key={x}>{x==='ALL'?'全部':x==='KEEP'?'保留使用':x==='EXCLUDE'?'排除':x==='SUSPECT_LEAKAGE'?'疑似泄漏':'特殊字段'}</option>)}</select></div>
    <div className="table-wrap"><table><thead><tr><th>字段</th><th>业务语义</th><th>数据类型</th><th>有效率</th><th>缺失率</th><th>唯一值比例</th><th>治理结论</th><th>原因</th><th>人工调整</th></tr></thead><tbody>{view.slice(0,500).map(g=><tr key={g.field}><td><b>{g.field}</b>{g.unique_ratio>.95&&<small className="risk-note">唯一值比例过高</small>}</td><td title={`技术原值：${g.semantic_type}`}><BusinessLabel value={g.semantic_type}/></td><td>{g.detected_type}</td><td>{(g.valid_rate*100).toFixed(1)}%</td><td>{(g.missing_rate*100).toFixed(1)}%</td><td>{(g.unique_ratio*100).toFixed(1)}%</td><td><BusinessLabel value={g.decision} className="tag"/></td><td className="reason">{g.reason}</td><td><select aria-label={`${g.field} 治理结论`} value={g.decision} onChange={e=>onChange(g.field,e.target.value)}>{decisions.slice(1).map(x=><option value={x} key={x}>{x==='KEEP'?'保留使用':x==='EXCLUDE'?'排除':x==='SUSPECT_LEAKAGE'?'疑似泄漏':x==='SPECIAL'?'特殊字段':x==='IDENTIFIER'?'标识字段':'需人工复核'}</option>)}</select></td></tr>)}</tbody></table></div>
  </div>;
}
