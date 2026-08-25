# Risk Strategy Agent 综合报告

更新时间：2026-08-25
当前结论：`FULL_FLOW_PASS`
统一测试入口：`python scripts/full_flow_acceptance.py`

## 1. 项目定位

Risk Strategy Agent 是面向风控策略、产品和业务人员的内部分析工作台，覆盖数据导入、字段治理、规则挖掘、风险分析助手、候选特征、质量验证、模型增量实验、实验决策、实验记忆和可恢复工作流。

LLM 只负责分析与建议；真实数据计算、特征生成、模型训练和实验比较由 Python 执行。系统不会因为 Agent 建议自动修改模型或上线策略。

## 2. 阶段能力

| 阶段 | 核心能力 | 状态 |
|---|---|---|
| Phase 1–4 | Agent Chat、上下文、特征编译、质量与增量验证 | READY_TO_FREEZE |
| Phase 5 | Decision Agent 与单因素实验反馈 | PHASE5_COMPLETE |
| Phase 6/6.5 | 实验记忆、效果归因、预测诊断与校准 | SURROGATE_VALIDATED |
| Phase 7A | 历史实验预测旁路观察 | SHADOW_MODE_COMPLETE |
| Phase 7B | 工作流、审批、恢复、幂等和审计 | WORKFLOW_ORCHESTRATION_COMPLETE |
| 产品化 | 中文映射、使用指南、统一验收 | WITH_MINOR_ISSUES |

## 3. 业务流程

```text
数据导入 → 数据质量与字段治理 → 规则与变量分析
→ 风险分析助手提出风险假设/候选特征 → 人工保存建议
→ 特征编译与生成 → 基础质量验证 → 增量效果验证
→ 模型实验与归因 → 实验决策 → 审批、反馈或回退
```

## 4. 安全边界

- 疑似贷后、逾期表现和泄漏字段会被治理或编译层阻断。
- 受控 DSL/AST 不执行任意 Python。
- 每次模型实验只改变一个主要因素。
- 高风险动作需要人工审批；失败实验可回退最近稳定版本。
- Workflow checkpoint 与业务模型回退分离。
- 历史实验预测不能覆盖 Phase 5 最终选择。
- LLM 密钥不写入源码或 SQLite，只从会话或环境变量解析。

## 5. 默认智谱绑定

| 配置 | 默认值 |
|---|---|
| Provider | `ZHIPU_OPENAI_COMPATIBLE` |
| Model | `glm-4-plus` |
| Base URL | `https://open.bigmodel.cn/api/paas/v4` |
| 密钥环境变量 | `ZHIPU_API_KEY` |

```powershell
$env:ZHIPU_API_KEY="你的智谱密钥"
$env:ZHIPU_MODEL="glm-4-plus"
```

后端启动时自动创建或刷新“智谱 GLM（默认）”绑定。数据库只保存环境变量引用名称，不保存密钥值。

## 6. 中文产品化

- 统一映射层：`frontend/src/i18n/businessLabels.ts`。
- `BusinessLabel` 显示中文主标签并保留英文技术值。
- 未知枚举显示“未知状态”，页面不会崩溃。
- Feature、Decision、Workflow、Shadow、Experiment Memory、Model、Governance、Rules 和 Agent Chat 主流程已中文化。
- AUC、KS、Lift、PSI、IV、Coverage、Bad Rate、OOT 已提供通俗解释。
- 使用指南包含八步快速开始、流程、页面、Agent 边界、审批、指标词典和 FAQ。

最近扫描：`50 mapped / 0 unmapped / 53 technical-only`。

## 7. 唯一全流程验收入口

```powershell
python scripts/full_flow_acceptance.py
```

脚本依次执行：全量 pytest、UI 中文映射扫描、前端 production build、Git 空白检查、源码密钥扫描和智谱默认绑定检查。结果写入 `test_artifacts/full_flow/latest.json`，不会调用真实 LLM，不产生模型费用。

## 8. 最近测试基线

- pytest：264 passed，10 warnings。
- Frontend Build：PASS。
- Happy Path：PASS。
- INVALID FIELD、LEAKAGE、REJECTED Feature：PASS。
- LLM/Model Failure、Budget Exhausted：PASS。
- Proposal Reject、Feature Review、Experiment Approval：PASS。
- Rollback、Cancel、Resume、Crash Resume、Idempotency：PASS。
- Shadow Guard、Secret Scan、Git Diff Check：PASS。

## 9. 历史实验预测

当前真实实验记录仍少。旧 Phase 6 门槛曾返回 `SURROGATE_INSUFFICIENT_DATA`；Phase 6.5 的结构、时间切分、校准和排序验证已通过。系统保持旁路观察，最终结果以真实实验和 Phase 5 规则为准。

## 10. 已知问题

- Vite 有 native config/CommonJS 和单 chunk 超过 500 kB 的非阻断警告。
- 当前环境没有可控浏览器实例，1366/1920 真实视觉验收未运行。
- Starlette/httpx、CPU 核数探测和 LightGBM 特征名存在非阻断警告。

## 11. 启动命令

```powershell
# 后端
conda activate py3.9
$env:ZHIPU_API_KEY="你的智谱密钥"
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

# 前端（新终端）
cd frontend
cmd /c npm run dev
```

访问 `http://127.0.0.1:5173`。

## 12. 最终结论

`FULL_FLOW_PASS`。核心功能、中文映射、Guide、Workflow、Rollback、Shadow Guard、候选特征安全编译、质量验证和反事实验证链路均已通过自动化验收。当前仅保留依赖库提示和前端包体积提示等非阻断警告。
