# Risk Strategy Agent V0.6

内部风控策略分析与验证工作台。根目录仅保留主接口 `app.py`；规则引擎模块统一位于 `core/`。V0.6 新增数据概览、字段质量可视化、严格规则评级、Jaccard Rule Group、变量分箱分析、导出和企业级 React 工作台。

## Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

V0.5 关键治理：贷后时间与逾期表现字段标记为 `POST_LOAN_FEATURE` / `SUSPECT_LEAKAGE`；数字手机号识别为 `IDENTIFIER`；camelCase 的 `maritalStatus` 不再因包含 `status` 被误杀；小于 300 样本的客群使用更严格 A 级门槛。人工覆盖保存在 `backend/uploads/{dataset_id}/governance_override.json`。

默认地址：`http://localhost:8000`，Swagger：`http://localhost:8000/docs`。

## Frontend

```bash
cd frontend
npm install
npm run dev
```

默认地址：`http://localhost:5173`。

## CLI

```bash
pip install -r requirements.txt
python app.py --input data.csv
```

支持 `--target`、`--segment-field`、`--output-dir`，默认分别为 `target7`、`is_old`、`outputs`。输出仅包含字段治理、候选规则和简洁报告三个文件。NEW/OLD 独立计算基准坏率、规则、Lift 与 Bootstrap。LLM 为可选解释层，V0 核心引擎不依赖 LLM。
V0.6 新增 API：

```text
GET /api/analysis/{dataset_id}/overview
GET /api/analysis/{dataset_id}/variables/{field}/bins
GET /api/analysis/{dataset_id}/rule-groups
GET /api/analysis/{dataset_id}/rule-groups/{rule_group_id}
GET /api/analysis/{dataset_id}/export/rules
GET /api/analysis/{dataset_id}/export/governance
GET /api/analysis/{dataset_id}/export/report
GET /api/analysis/{dataset_id}/export/all
```
