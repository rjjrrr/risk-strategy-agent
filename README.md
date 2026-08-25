# Risk Strategy Agent

Risk Strategy Agent 是一个面向风控策略、数据分析和模型实验的本地工作台。系统覆盖数据导入、字段治理、规则挖掘、Agent 风险分析、候选特征生成、质量验证、特征级反事实实验、实验决策、实验记忆和可恢复工作流。

当前验收状态：`FULL_FLOW_PASS`。详细能力与验收结论见 [RISK_STRATEGY_AGENT_REPORT.md](RISK_STRATEGY_AGENT_REPORT.md)。

## 核心能力

- CSV、XLSX、XLS 数据导入与数据健康检查。
- NEW / OLD 客群拆分、字段治理、变量扫描和规则挖掘。
- 规则稳定性、OOT 验证、相似规则聚类和代表规则选择。
- 智谱 GLM 默认绑定，以及通用对话、风险分析、实验决策三类助手。
- LLM 风险假设和候选特征建议，所有建议必须人工保存。
- 安全特征 DSL、公式编译、能力缺口识别和可审计执行。
- 基础质量验证：有效率、缺失率、IV、PSI、Lift、相关性和新颖性。
- 特征级反事实验证：固定数据切分、模型参数和随机种子，对比加入或移除特征前后的 AUC、KS、Lift 和 PSI。
- LR / LightGBM 基线、最多三轮模型实验、人工审批和版本回退。
- 实验记忆、效果归因、历史实验辅助预测和 LangGraph 工作流编排。
- 中文业务映射、使用指南、统一综合报告和全流程验收脚本。

## 系统边界

LLM 只负责解释证据、提出假设和生成候选建议。数据计算、特征生成、模型训练、指标比较和回退均由 Python 确定性代码执行。

系统不会因为 Agent 的回复自动修改生产模型或上线策略。候选特征生成、模型实验和高风险动作均保留人工确认与审计记录。

## 项目结构

```text
backend/                  FastAPI 接口与应用服务
core/                     规则、特征、模型、决策和工作流核心逻辑
frontend/                 React + TypeScript + Vite 前端
scripts/full_flow_acceptance.py
                          唯一全流程验收入口
tests/                    自动化回归测试
app.py                    独立 CLI 规则挖掘入口
RISK_STRATEGY_AGENT_REPORT.md
                          当前综合报告
```

上传数据、运行数据库、模型产物、分析输出和测试结果默认被 Git 忽略，不会提交到仓库。

## 环境要求

- Windows PowerShell
- Python 3.9 或兼容版本
- Node.js 18+
- npm
- 推荐使用 Conda 环境 `py3.9`

## 安装

在项目根目录执行：

```powershell
conda activate py3.9
pip install -r requirements.txt

cd frontend
cmd /c npm install
cd ..
```

## 智谱 GLM 配置

复制环境变量模板，或直接在启动后端的 PowerShell 中设置：

```powershell
$env:ZHIPU_API_KEY="你的智谱 API Key"
$env:ZHIPU_MODEL="glm-4-plus"
```

后端会自动创建“智谱 GLM（默认）”绑定。API Key 仅从环境变量或前端运行时输入读取，不应写入源码、README、数据库或 Git 提交。

## 启动项目

终端 1：启动后端。

```powershell
cd "C:\path\to\风控Agent_2"
conda activate py3.9
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

后端地址：

- API：`http://127.0.0.1:8000`
- Swagger：`http://127.0.0.1:8000/docs`
- OpenAPI：`http://127.0.0.1:8000/openapi.json`

终端 2：启动前端。

```powershell
cd "C:\path\to\风控Agent_2\frontend"
cmd /c npm run dev
```

浏览器访问 `http://127.0.0.1:5173`。

Windows 环境建议先使用无热重载方式启动后端，避免旧 Uvicorn reload 子进程继续占用 8000 端口。

## 推荐使用流程

1. 在“数据导入”上传 CSV 或 Excel。
2. 完成数据概览、字段映射和数据健康检查。
3. 运行字段治理、变量扫描、候选规则、稳定性、规则组、评级和报告。
4. 在“风险分析助手”生成风险假设和候选特征建议。
5. 人工点击“保存候选特征”。
6. 在“候选特征”编译安全公式并确认生成特征。
7. 运行质量验证。
8. 对通过门禁且具备模型资格的特征运行 LR 或 LightGBM 反事实验证。
9. 在“模型实验”初始化基线并运行后续实验。
10. 在“实验决策助手”“实验记忆”和“风险研究工作流”查看决策、归因和完整审计记录。

## 反事实验证说明

反事实验证位于“候选特征 → 已生成与验证”。系统会保持以下条件一致：

- 相同 DEV / OOT 数据切分。
- 相同模型参数。
- 相同随机种子。
- 除目标候选特征外，相同的基线特征池。

可执行两类实验：

- `FEATURE_ADD`：基线特征与“基线 + 候选特征”对比。
- `FEATURE_REMOVE`：包含该特征与移除该特征后的消融对比。

结果展示 OOT AUC、OOT KS、Lift@10、训练与验证差距及评分 PSI 的使用前、使用后和增量变化。

## CLI 规则挖掘

不启动前后端也可以直接运行基础规则挖掘：

```powershell
python app.py --input data.csv --target target7 --segment-field is_old --output-dir outputs
```

## 测试与验收

运行完整验收：

```powershell
python scripts/full_flow_acceptance.py
```

该脚本执行：

- 全量 Python 回归测试。
- 前端生产构建。
- 中文业务映射检查。
- Git 空白字符检查。
- 密钥与敏感文件扫描。
- 智谱默认绑定和密钥不落盘检查。

当前基线为 `264 passed`，最终输出应包含：

```text
FULL_FLOW_PASS
```

单独运行测试或前端构建：

```powershell
python -m pytest -q

cd frontend
cmd /c npm run build
```

## 常见问题

### npm.ps1 无法执行

PowerShell 执行策略可能拦截 `npm.ps1`，使用：

```powershell
cmd /c npm run dev
```

### Port 5173 或 8000 is already in use

```powershell
netstat -ano | findstr :5173
netstat -ano | findstr :8000
taskkill /PID 查到的PID /F
```

### `/api/model-agent/...` 返回 404

检查当前后端版本和路由：

```powershell
$api = Invoke-RestMethod "http://127.0.0.1:8000/openapi.json"
$api.info.title
($api.paths.PSObject.Properties.Name | Where-Object { $_ -like "*model-agent*" }).Count
```

正常情况下标题为 `Risk Strategy Agent V1.0`，模型实验路由数量应大于 0。如果仍显示 V0.5，请结束旧后端进程并从当前项目根目录重新启动。

### 后端重启后旧数据集不可用

当前上传数据集保存在运行内存中，后端重启后需要重新导入原始数据。上传原始文件和运行产物不会提交到 Git。

## 数据与密钥安全

以下内容已在 `.gitignore` 中排除：

- `.env` 和本地配置。
- API Key、证书和私钥。
- `backend/uploads/` 上传原始数据。
- `backend/model_agent/` 模型与实验产物。
- `backend/runtime/` SQLite 运行数据库。
- `outputs/` 和 `test_artifacts/` 分析及测试结果。
- `frontend/node_modules/`、`frontend/dist/` 和 TypeScript 构建缓存。

提交前建议运行：

```powershell
git status --short
python scripts/full_flow_acceptance.py
```

## 许可证与使用范围

本项目用于风控策略研究、内部分析和实验验证。任何生产上线、策略变更或永久特征移除均应经过独立审批和业务验证。
