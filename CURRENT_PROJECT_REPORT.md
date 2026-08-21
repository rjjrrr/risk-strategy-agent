# Risk Strategy Agent 当前项目报告

报告日期：2026-08-21  
当前开发分支：`feature/ai-model-agent-v1.1`  
分支基线提交：`53df788 fix: stabilize phase 1 agent chat runtime`  
当前工作区状态：Phase 2 修改已完成并通过验收，但尚未提交 Git。

## 1. 当前结论

Risk Strategy Agent 当前已具备从数据导入、字段治理、规则挖掘、规则聚类、模型实验到 LLM Agent Chat 的完整基础链路。

本轮 Phase 2 已完成以下核心升级：

- 建立确定性、模块化、NEW-only 的 Context Builder。
- Analysis Agent 使用严格的结构化输出协议。
- 假设和特征建议只能形成待人工处理的 Proposal，不会直接执行。
- 增加无效字段、重复特征、泄漏风险和原始时间字段保护。
- 前端可以预览上下文来源、预算、条目和调用 Trace。
- 完成大上下文压力测试、全量自动化测试、前端构建和真实智谱调用验收。

综合判断：后端核心链路和自动化验收已达到 Phase 2 交付条件；正式合并前仍建议完成一次浏览器人工 UI 验收并提交当前分支。

## 2. 当前已有能力

### 2.1 数据与规则分析

- CSV、XLSX、XLS 数据读取。
- Target、Segment 配置和 NEW / OLD 客群映射。
- 数据健康检查、字段治理和人工治理覆盖。
- 数值型、类别型变量扫描。
- 候选规则生成、Bootstrap 稳定性和 OOT 评估。
- 基于 Jaccard 的规则去重、相似规则识别和规则组聚类。
- 规则评级、规则报告和分析产物导出。
- 大数据可挖掘、不可挖掘和规则聚类三类回归场景。

### 2.2 Model Agent

- Semantic、Hypothesis、Feature、Experiment、Diagnosis、Approval Registry。
- LR 和 LightGBM 基线及实验模型。
- DEV / OOT AUC、KS、Lift、PSI 和模型差距评估。
- CURRENT、BEST、LAST_STABLE 状态指针。
- 实验拒绝、回滚、人工审批和审计时间线。
- Feature lineage、公式、来源字段和可重建信息。

### 2.3 Agent Chat Runtime

- General Chat、Analysis Agent、Decision Agent 三种入口。
- OpenAI、DeepSeek、Qwen、Zhipu 和自定义 OpenAI-compatible Binding。
- Binding 切换、Agent 默认 Binding、连接测试和显式 fallback。
- 同步消息、SSE、Stop、Retry 和会话历史。
- Provider、Binding、Model、Prompt、Token、延迟和错误 Trace。
- Mock、LLM、Deterministic 三类 Runtime 明确区分。
- API Key 仅保存在当前进程内存，不写入 SQLite 或 Git 文件。

## 3. Phase 2 Context Builder

Context Builder 已拆分为独立模块：

- `schemas.py`：ContextRequest、ContextItem、ContextBundle。
- `sources.py`：统一上下文来源。
- `ranking.py`：查询、字段焦点、优先级和来源相关性排序。
- `dedup.py`：来源 ID 与内容 Hash 去重。
- `compression.py`：结构化压缩，不截断半个 JSON。
- `budget.py`：按来源 Top-K 和软 Token 预算筛选。
- `serialization.py`：稳定 JSON、Hash 和 Token 估算。
- `builder.py`：统一编排和版本信息。

当前支持的上下文来源：

1. `DATASET_SUMMARY`
2. `DATA_HEALTH`
3. `GOVERNANCE`
4. `VARIABLE_PROFILE`
5. `RULE_SUMMARY`
6. `RULE_GROUP`
7. `FEATURE_REGISTRY`
8. `HYPOTHESIS_REGISTRY`
9. `EXPERIMENT_HISTORY`
10. `MODEL_STATE`
11. `CONVERSATION_MEMORY`

关键约束：

- 风控分析数据强制使用 NEW 客群。
- 不向 LLM 发送 DataFrame 原始行。
- 默认预算为 8,000 估算 Token，最大允许 12,000。
- 每个来源默认最多保留 20 个条目。
- 最近只向 Runtime 传递 8 条完整消息，更早消息使用确定性摘要。
- Context 使用稳定 Hash，并在源数据变化后自动失效缓存。
- 保存 Context ID、Hash、条目数、来源数和估算 Token，支持审计回溯。

## 4. Analysis Agent 与 Proposal 保护

Analysis Agent 当前必须返回以下结构：

- `analysis_summary`
- `semantic_findings[]`
- `hypotheses[]`
- `feature_proposals[]`
- `warnings[]`
- `missing_information[]`

输出先经过 Pydantic 校验。首次失败后只允许一次 JSON 修复；同时兼容 Provider 返回的 Markdown JSON 代码块。

Proposal 保护规则：

| 场景 | 保护码 | 处理方式 |
|---|---|---|
| 来源字段不存在 | `INVALID_SOURCE_FIELD` | 禁止保存 |
| 特征公式和来源重复 | `DUPLICATE_FEATURE` | 禁止重复保存并返回已有 Feature ID |
| 假设语义及来源重复 | `DUPLICATE_HYPOTHESIS` | 禁止重复保存 |
| 字段存在泄漏风险 | `LEAKAGE_RISK` | 禁止保存 |
| DATETIME 作为 RAW 特征 | `DATETIME_RAW_FORBIDDEN` | 转人工 REVIEW |
| 需要特征工程 | `NEEDS_FEATURE_ENGINE` | 允许保存 Proposal，不执行 |
| 可以进入编译准备 | `READY_FOR_COMPILATION` | 允许保存 Proposal，不执行 |

人工接受后：

- Hypothesis Registry 状态为 `PROPOSED`。
- Feature Registry 状态为 `PROPOSED`。
- 不运行特征计算。
- 不发起实验。
- 不训练或替换模型。

## 5. API 状态

新增 Context API：

```text
POST /api/context/build
GET  /api/context/{context_id}
GET  /api/context/{context_id}/preview
```

Agent Chat 主要 API：

```text
POST /api/agent-chat/conversations
GET  /api/agent-chat/conversations
POST /api/agent-chat/conversations/{id}/messages
POST /api/agent-chat/conversations/{id}/messages/stream
POST /api/agent-chat/messages/{message_id}/cancel
POST /api/agent-chat/conversations/{id}/messages/{message_id}/retry
GET  /api/agent-chat/proposals
POST /api/agent-chat/proposals/{proposal_id}/accept
POST /api/agent-chat/proposals/{proposal_id}/reject
GET  /api/agent-chat/calls
```

## 6. 前端状态

Agent Chat Workbench 当前支持：

- 会话创建、搜索、重命名和删除。
- Agent 与 Model Binding 独立切换。
- Dataset 绑定。
- Context 来源开关、字段焦点和 Token 预算。
- Context Preview、条目数量、来源列表和 Context Hash。
- Analysis Summary、Semantic Findings、Hypotheses 分区展示。
- Hypothesis / Feature Proposal 卡片。
- Save Hypothesis、Save Feature Proposal 和 Reject。
- 被保护规则阻断的 Proposal 禁止保存。
- Message Trace 展示 Context ID、Hash、条目数、估算 Token 和来源。

## 7. 自动化验证结果

### 7.1 Python 全量测试

```text
85 passed, 6 warnings
```

覆盖范围包括：

- V0/V0.7 数据治理和规则挖掘。
- 规则聚类和大数据回归。
- Model Agent 状态、特征、模型、实验和 API。
- Phase 1 Agent Chat、Binding、SSE、Stop、Retry 和 Trace。
- Phase 2 Context 预算、缓存、NEW-only 和 Proposal Guard。
- 100 个条目/来源的上下文膨胀测试。
- Markdown JSON 代码块兼容测试。

当前警告属于依赖或运行环境提示：

- Starlette TestClient 弃用提示。
- loky 无法获取物理核心数。
- LightGBM/sklearn Feature Name 提示。

均未导致测试失败。

### 7.2 前端构建

```text
TypeScript build: PASS
Vite production build: PASS
```

非阻断提示：

- Vite 配置未来版本将调整 native config loader 行为。
- 主 JavaScript Bundle 大于 500 KB，后续可使用页面级动态加载优化。

## 8. 真实智谱验收

验收 Provider：`ZHIPU_OPENAI_COMPATIBLE`  
验收模型：`glm-4-plus`  
验收数据：本地大数据可挖掘测试集 `01_mineable/source.csv`  
该数据为合成测试数据，不代表生产客群表现。

验收结果：

| 检查项 | 结果 |
|---|---:|
| NEW-only Context | PASS |
| Pydantic 结构化输出 | PASS |
| 至少 3 条风险假设 | PASS，实际 3 条 |
| Context 不超过预算 | PASS，估算 5,889 Token |
| 不自动执行 Registry | PASS |
| Feature Proposal | 4 条 |
| 待人工 Proposal | 7 条 |
| LLM Call | SUCCESS |

测试数据中的主要分析发现：

| 信号 | NEW 客群证据 | 判断 |
|---|---|---|
| 低月收入 | `monthly_income <= 3187.36`，坏账率 29.87%，基准 16.83%，Lift 1.775 | 高置信风险信号 |
| RED 设备风险 | 坏账率 35.63%，Lift 2.118 | 高置信风险信号 |
| P5 地域组 | 坏账率 23.41%，Lift 1.391 | 中高风险信号 |

生成的特征建议：

| 特征 | 状态 |
|---|---|
| `income_stability_index` | `NEEDS_FEATURE_ENGINE` |
| `device_risk_weighted_score` | `READY_FOR_COMPILATION` |
| `province_risk_indicator` | `READY_FOR_COMPILATION` |
| `low_income_device_risk_combo` | `NEEDS_FEATURE_ENGINE` |

以上内容均只保存在 Proposal 层，没有执行计算或模型训练。

## 9. 安全与隐私检查

- 智谱 API Key 未写入项目代码。
- API Key 未写入验收 JSON。
- API Key 未写入 SQLite Binding 数据。
- `backend/runtime/**`、`backend/model_agent/**`、`backend/uploads/**` 和 `test_artifacts/**` 均被 Git 忽略。
- Context 不包含原始业务数据行或字段样例值。
- `git diff --check` 未发现空白错误。

## 10. 当前未提交修改

Phase 2 当前仍位于工作区，尚未形成新 Git 提交，主要包括：

- `core/context/` 全部 Context Builder 模块。
- Context Service 和 Context API。
- Analysis Agent Schema、Prompt、Runtime 和 Proposal Guard。
- SQLite Context Trace 字段迁移。
- Agent Chat 前端 Context Preview 和 Proposal UI。
- Phase 2 自动化测试与真实验收脚本。
- Change #039 至 Change #042 变更记录。

因此当前远程分支如果仍停留在 `53df788`，不会包含本报告描述的 Phase 2 工作区修改。

## 11. 已知问题与风险

1. 尚未完成真实浏览器鼠标操作的最终 UI 人工验收；当前证据为 TypeScript/Vite 构建和后端接口测试。
2. Context Token 为保守估算值，不是智谱官方 tokenizer 的精确结果。
3. 真实验收 JSON 在部分 Windows 终端中可能出现中文乱码显示，但结构化字段、数值和校验状态正常；建议统一终端与编辑器为 UTF-8。
4. 前端 Bundle 约 1.45 MB，后续应进行页面拆包。
5. Model/Experiment Context 只有对应 Registry 已存在时才会进入上下文；缺失时 Analysis Agent 必须通过 `missing_information` 明确披露。
6. 当前 Phase 2 不包含 LangGraph、多 Agent 自动决策闭环、自动特征执行或自动训练，这些能力也不应在本阶段隐式开启。

## 12. 建议的下一步

建议按以下顺序处理：

1. 启动前后端，人工验证 Context Drawer、Trace、Proposal 保存与拒绝交互。
2. 检查 Phase 2 Git Diff 和敏感信息扫描结果。
3. 在当前功能分支提交 Phase 2，不直接修改 `main`。
4. 推送功能分支并保留 Phase 1、Phase 2 独立可下载版本。
5. 通过评审后再决定是否合并到 `main` 或创建正式版本 Tag。

## 13. 常用验证命令

```powershell
# 后端测试
python -m pytest -q

# 前端构建
cd frontend
cmd /c npm run build
cd ..

# 查看当前分支和修改
git branch --show-current
git status --short
git diff --check

# 真实智谱验收：密钥只放在当前进程环境变量中
$env:ZHIPU_API_KEY="<your-key>"
python scripts/phase2_real_acceptance.py
Remove-Item Env:ZHIPU_API_KEY
```

真实验收产物保存在：

```text
test_artifacts/phase2_acceptance/acceptance.json
```

该目录已被 `.gitignore` 排除。
