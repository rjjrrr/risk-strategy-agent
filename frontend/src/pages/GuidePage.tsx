import {AlertTriangle,ArrowRight,Bot,CheckCircle2,HelpCircle,Route,ShieldCheck} from 'lucide-react';
import {MetricHelp} from '../components/BusinessLabel';

type Props={onNavigate:(page:string)=>void};
const steps=[
  ['上传数据','导入待分析的 CSV 或 Excel 数据。','确认目标字段、客群字段和样本量。','首次分析或更换数据时。','import','前往数据页面'],
  ['检查数据质量','判断数据是否适合继续分析。','缺失率、异常值和字段有效率。','发现质量提示时先确认数据来源。','overview','前往数据概览'],
  ['查看字段和规则','识别不可用、疑似泄漏字段和高风险客群。','字段治理结论、覆盖率、坏账率与 Lift。','复核疑似泄漏或低样本规则时。','rules','前往规则中心'],
  ['寻找风险信号','让风险分析助手结合数据概况、变量表现、规则和历史实验提出建议。','风险发现、风险假设和候选特征。','需要补充业务解释或探索方向时。','agent-chat','前往风险分析助手'],
  ['保存分析建议','把经过人工判断的风险假设或候选特征保存下来。','建议理由、来源字段和校验状态。','确认建议值得进入计算验证时。','agent-chat','查看待处理建议'],
  ['生成并验证特征','将候选特征转换为受控计算逻辑，并检查质量和泄漏风险。','有效率、缺失率、IV、PSI 与可用模型。','编译、生成和验证均需人工触发。','feature-engine','前往候选特征'],
  ['查看增量实验','对比加入或移除特征前后的同条件模型结果。','OOT AUC、OOT KS、Lift 和稳定性变化。','决定特征是否真正带来增益时。','feature-engine','查看增量效果验证'],
  ['查看决策建议','根据模型问题与历史实验确定下一项最值得验证的动作。','诊断、建议动作、证据、风险和审批要求。','高风险操作必须由你确认。','decision-loop','前往实验决策助手'],
] as const;

const faqs=[
  ['为什么助手建议的特征没有自动生成？','助手只负责分析和建议。保存、编译、生成与实验均由 Python 系统执行，并保留人工确认。'],
  ['为什么某个特征被拒绝？','常见原因包括来源字段无效、数据泄漏、重复、缺失严重或增量效果不足；请查看中文原因和技术原值。'],
  ['为什么特征有效但没有进入 LR？','特征可能不满足线性模型的稳定性、共线性或数据类型要求，但仍可能适用于 LightGBM。'],
  ['为什么训练集效果很好但系统仍说不稳定？','训练集提升可能来自过拟合。系统还会检查较晚时间的 OOT 数据、PSI 和训练—验证差距。'],
  ['为什么系统建议回退？','当前实验可能降低效果、增加漂移或超过风险边界；回退只恢复业务模型状态，不删除审计记录。'],
  ['为什么历史实验预测和最终结果不同？','历史实验预测只是基于相似实验的辅助估计，新数据和新特征可能不同；真实模型实验始终是最终依据。'],
  ['为什么有些操作需要人工确认？','模型切换、回退、接受建议等操作会影响后续实验路径，因此流程会暂停并等待明确审批。'],
];

export default function GuidePage({onNavigate}:Props){
  return <div className="page guide-page">
    <section className="guide-hero"><div><span>业务人员 · 10 分钟快速上手</span><h2>Risk Strategy Agent 使用指南</h2><p>从数据导入到风险特征验证，快速完成一次风控分析流程。</p></div><button onClick={()=>onNavigate('import')}>开始使用<ArrowRight size={16}/></button></section>
    <nav className="guide-toc" aria-label="使用指南目录">{[['quick','快速开始'],['flow','完整工作流程'],['pages','页面说明'],['metrics','指标说明'],['agent','Agent 怎么用'],['approval','人工审批'],['faq','常见问题']].map(([id,label])=><a key={id} href={`#${id}`}>{label}</a>)}</nav>

    <section id="quick" className="guide-section"><h3>1. 快速开始</h3><p className="muted">按顺序完成以下八步。页面按钮只负责导航，不会自动运行分析、训练模型或接受建议。</p><div className="guide-steps">{steps.map((x,i)=><article key={x[0]}><i>{i+1}</i><div><h4>{x[0]}</h4><dl><dt>这是做什么？</dt><dd>{x[1]}</dd><dt>主要看什么？</dt><dd>{x[2]}</dd><dt>什么时候需要你操作？</dt><dd>{x[3]}</dd></dl><button className="secondary" onClick={()=>onNavigate(x[4])}>{x[5]}<ArrowRight size={14}/></button></div></article>)}</div></section>

    <section id="flow" className="guide-section"><h3>2. 完整工作流程</h3><div className="guide-flow"><span>风险假设</span><ArrowRight/><span>候选特征</span><ArrowRight/><span>系统计算</span><ArrowRight/><span>质量验证</span><ArrowRight/><span>模型实验</span><ArrowRight/><span>结果反馈</span></div><div className="guide-callout"><Route/><div><b>工作流负责串联已有步骤</b><p>分析 → 特征 → 验证 → 实验 → 结果反馈。遇到需要人工确认的位置，流程会自动暂停；工作流断点可恢复。</p></div><button onClick={()=>onNavigate('workflow-run')}>前往工作流</button></div></section>

    <section id="pages" className="guide-section"><h3>3. 页面说明</h3><div className="guide-cards"><article><h4>规则中心</h4><p>查看某类客户是否表现出明显更高风险，重点关注覆盖率、坏账率、Lift 和稳定性。</p></article><article><h4>风险分析助手</h4><p>结合数据概况、变量表现、规则结果和历史实验，提出风险发现、风险假设与候选特征。</p></article><article><h4>候选特征</h4><p>把已保存建议编译成受控计算逻辑，执行质量验证和模型增量实验。计算结果来自 Python。</p></article><article><h4>实验决策助手</h4><p>根据当前模型问题和历史实验结果，建议下一步最值得验证的动作。</p></article><article><h4>历史实验预测</h4><p>根据过去实验估计新实验可能是否有效，目前只作辅助参考，真实模型实验是最终依据。</p></article><article><h4>风险研究工作流</h4><p>自动串联已有步骤，并记录节点状态、审计时间线和人工审批点。</p></article></div></section>

    <section id="metrics" className="guide-section"><h3>4. 风控指标词典</h3><div className="metric-dictionary">{(['AUC','KS','Lift','Bad Rate','Coverage','IV','PSI','OOT'] as const).map(name=><article key={name}><MetricHelp name={name}/><p>{name==='Bad Rate'?'规则命中客群中的坏账率或逾期率，沿用当前数据业务口径。':name==='Coverage'?'规则命中的样本占总体样本的比例。':undefined}</p></article>)}</div><div className="guide-warning"><AlertTriangle/><p><b>判断结果时请注意：</b>不要只看单个 Lift；不要只看训练集 AUC；不要使用泄漏字段；不要因为 Agent 建议就直接上线。</p></div></section>

    <section id="agent" className="guide-section"><h3>5. Agent 怎么用</h3><div className="guide-boundary"><div><Bot/><h4>风险分析助手负责</h4><p>阅读压缩后的分析证据，解释风险信号，提出假设与候选特征建议。</p></div><div><CheckCircle2/><h4>Python 系统负责</h4><p>真实的数据计算、质量校验、特征生成和模型实验，结果可审计。</p></div><div><ShieldCheck/><h4>明确边界</h4><p>Agent 不会直接修改模型或上线策略；原始明细不会因对话而自动发送。</p></div></div><h4>“这个特征到底有没有用？”</h4><p>增量效果验证会在其他实验条件一致时，分别训练“不使用该特征”和“使用该特征”的模型，再比较 AUC、KS 与 Lift，判断真实边际贡献。技术上称为 Counterfactual。</p><button onClick={()=>onNavigate('agent-chat')}>前往风险分析助手</button></section>

    <section id="approval" className="guide-section"><h3>6. 人工审批说明</h3><p>系统可以建议验证特征、切换模型、停止探索或回退版本，但高风险操作仍需要人工确认。</p><div className="approval-grid"><span><b>同意并继续</b>允许流程执行当前待审批动作。</span><span><b>拒绝</b>不执行当前建议，审计记录仍保留。</span><span><b>重新尝试</b>从失败节点再次执行。</span><span><b>回退版本</b>恢复最近稳定的业务模型状态。</span><span><b>停止流程</b>取消后续节点，不删除既有结果。</span><span><b>继续运行</b>从已保存的工作流断点恢复。</span></div></section>

    <section id="faq" className="guide-section"><h3>7. 常见问题</h3>{faqs.map(([q,a])=><details key={q}><summary><HelpCircle size={15}/>{q}</summary><p>{a}</p></details>)}</section>
  </div>;
}
