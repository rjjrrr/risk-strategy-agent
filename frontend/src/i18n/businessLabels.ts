export type BusinessLabel={label:string;description?:string};

export const validationLabels:Record<string,BusinessLabel>={
  PROMISING:{label:'值得验证'},EXPLORATORY:{label:'探索性特征'},REVIEW:{label:'需人工复核'},
  REJECTED:{label:'不建议使用'},VALIDATED:{label:'已完成验证'},NOT_RUN:{label:'尚未验证'},
};

export const creditLabels:Record<string,BusinessLabel>={
  POSITIVE:{label:'正向有效'},NEUTRAL:{label:'暂无明显增益'},NEGATIVE:{label:'负向影响'},
  UNSTABLE:{label:'效果不稳定'},SUPPORTED:{label:'假设得到支持'},
  PARTIALLY_SUPPORTED:{label:'假设部分成立'},INCONCLUSIVE:{label:'暂无法判断'},FAILED:{label:'执行失败'},
};

export const diagnosisLabels:Record<string,BusinessLabel>={
  DATA_QUALITY:{label:'数据质量问题'},LEAKAGE:{label:'数据泄漏风险'},LOW_SIGNAL:{label:'有效信号不足'},
  OVERFITTING:{label:'模型过拟合'},FEATURE_DRIFT:{label:'特征漂移'},REDUNDANCY:{label:'特征冗余'},
  SEGMENT_MIXTURE:{label:'客群混杂'},MODEL_MISMATCH:{label:'模型不匹配'},
  UNSTABLE_GAIN:{label:'增益不稳定'},INSUFFICIENT_SAMPLE:{label:'样本不足'},
  NO_ACTION_REQUIRED:{label:'暂无需进一步操作'},
};

export const actionLabels:Record<string,BusinessLabel>={
  TEST_FEATURE:{label:'验证候选特征'},TEST_HYPOTHESIS:{label:'验证风险假设'},
  REMOVE_FEATURE_ABLATION:{label:'测试移除特征'},FEATURE_REMOVE:{label:'测试移除特征'},FEATURE_ADD:{label:'验证候选特征'},
  MODEL_SWITCH:{label:'尝试其他模型'},MODEL_TUNE:{label:'模型参数调整'},
  DATA_CLEAN_PROPOSAL:{label:'数据清洗建议'},FEATURE_TRANSFORM_PROPOSAL:{label:'特征转换建议'},
  REQUEST_ANALYSIS:{label:'请求进一步分析'},REQUEST_MORE_DATA:{label:'需要补充数据'},
  ROLLBACK:{label:'回退到稳定版本'},STOP_EXPLORATION:{label:'停止继续探索'},NO_ACTION:{label:'暂不操作'},
};

export const modelStateLabels:Record<string,BusinessLabel>={
  CURRENT_STATE:{label:'当前版本'},BEST_STATE:{label:'当前最佳版本'},LAST_STABLE_STATE:{label:'最近稳定版本'},
};

export const stopReasonLabels:Record<string,BusinessLabel>={
  HIGH_CONFIDENCE_HYPOTHESES_EXHAUSTED:{label:'高置信度假设已验证完毕'},
  NO_UNTESTED_HYPOTHESIS:{label:'暂无可验证的风险假设'},
  NO_VALIDATED_FEATURE_FOR_HYPOTHESIS:{label:'当前假设没有通过验证的特征'},
  MAX_AGENT_ROUNDS_REACHED:{label:'已达到最大实验轮次'},
  TWO_ROUNDS_WITHOUT_MATERIAL_IMPROVEMENT:{label:'连续两轮没有显著提升'},
  EXPERIMENT_BUDGET_EXHAUSTED:{label:'实验预算已用完'},
  HUMAN_APPROVAL_PENDING:{label:'等待人工审批'},HUMAN_STOP:{label:'已由人工停止'},
};

export const workflowLabels:Record<string,BusinessLabel>={
  NOT_STARTED:{label:'未开始'},RUNNING:{label:'运行中'},SUCCESS:{label:'已完成'},FAILED:{label:'运行失败'},
  WAITING:{label:'等待人工处理'},WAITING_APPROVAL:{label:'等待人工审批'},SKIPPED:{label:'已跳过'},
  STALE:{label:'结果已过期'},CANCELLED:{label:'已取消'},CANCEL_REQUESTED:{label:'正在请求取消'},
  COMPLETED:{label:'已完成'},STOPPED:{label:'已停止'},PENDING:{label:'待处理'},APPROVED:{label:'已同意'},
};

export const surrogateLabels:Record<string,BusinessLabel>={
  SHADOW_ONLY:{label:'旁路观察'},ACTIVE_CANDIDATE:{label:'候选预测模型'},ACTIVE:{label:'已启用辅助预测'},
  INSUFFICIENT_DATA:{label:'历史实验不足'},OUT_OF_DISTRIBUTION:{label:'与历史实验差异较大'},
  PHASE5_FALLBACK:{label:'当前仍按系统规则执行'},PREDICTION_DISABLED:{label:'历史实验预测未启用'},
};

export const approvalLabels:Record<string,BusinessLabel>={
  APPROVE:{label:'同意并继续'},REJECT:{label:'拒绝'},RETRY:{label:'重新尝试'},ROLLBACK:{label:'回退版本'},
  STOP:{label:'停止流程'},RESUME:{label:'继续运行'},REQUIRED:{label:'需要人工确认'},NOT_REQUIRED:{label:'无需人工确认'},
};

export const commonLabels:Record<string,BusinessLabel>={
  YES:{label:'是'},NO:{label:'否'},HIGH:{label:'高'},MEDIUM:{label:'中'},LOW:{label:'低'},
  STRONG:{label:'稳定'},WEAK:{label:'偏弱'},NOT_AVAILABLE:{label:'暂无结果'},
  SUPPORTED_TEMPLATE:{label:'支持的标准模板'},COMPOSABLE_DSL:{label:'可组合计算逻辑'},
  INVALID:{label:'无效'},DUPLICATE:{label:'重复'},LEAKAGE_RISK:{label:'存在泄漏风险'},
  KEEP:{label:'保留使用'},EXCLUDE:{label:'排除'},SUSPECT_LEAKAGE:{label:'疑似泄漏'},SPECIAL:{label:'特殊字段'},
  IDENTIFIER:{label:'标识字段'},ALL:{label:'全部'},ACCEPTED:{label:'已接受'},ENABLED:{label:'已启用'},DISABLED:{label:'已停用'},
  ACTIVE:{label:'运行中'},READY:{label:'准备就绪'},STOPPED:{label:'已停止'},
};

export const metricHelp:Record<string,string>={
  AUC:'衡量模型整体排序能力，越接近 1 通常区分能力越强。',
  KS:'衡量好坏客户区分能力，数值越高通常说明模型区分能力越强。',
  Lift:'目标客群风险相对总体平均风险的倍数，用于判断策略筛选效率。',
  PSI:'衡量不同时间或样本间的分布变化，越高说明稳定性风险越大。',
  IV:'衡量变量对风险结果的区分信息量，用于辅助筛选有效变量。',
  Coverage:'规则命中的样本占总体样本的比例。',
  'Bad Rate':'规则命中客群中的坏账率或逾期率，沿用当前数据业务口径。',
  OOT:'时间外验证集：使用较晚时间的数据验证模型，观察未来数据上的稳定性。',
};

const groups=[validationLabels,creditLabels,diagnosisLabels,actionLabels,modelStateLabels,stopReasonLabels,workflowLabels,surrogateLabels,approvalLabels,commonLabels];
export const allBusinessLabels=Object.assign({},...groups) as Record<string,BusinessLabel>;

export function businessLabel(value:unknown,map?:Record<string,BusinessLabel>):BusinessLabel{
  const raw=String(value??'').trim();
  if(!raw)return {label:'暂无信息'};
  return map?.[raw]||allBusinessLabels[raw]||{label:'未知状态',description:`系统返回了尚未配置的状态：${raw}`};
}

export function displayLabel(value:unknown,map?:Record<string,BusinessLabel>):string{
  return businessLabel(value,map).label;
}
