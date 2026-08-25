# Risk Strategy Agent

面向风控策略、产品和业务人员的数据分析、规则挖掘、候选特征验证、模型实验与工作流平台。完整能力和验收结论见 `RISK_STRATEGY_AGENT_REPORT.md`。

## 安装

```powershell
conda activate py3.9
pip install -r requirements.txt
cd frontend
cmd /c npm install
```

## 默认智谱配置

```powershell
$env:ZHIPU_API_KEY="你的智谱密钥"
$env:ZHIPU_MODEL="glm-4-plus"
```

后端会自动创建“智谱 GLM（默认）”绑定。密钥只从环境变量读取，不写入仓库或数据库。

## 启动后端

在项目根目录执行：

```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

API：`http://127.0.0.1:8000`，Swagger：`http://127.0.0.1:8000/docs`。

## 启动前端

新开终端：

```powershell
cd frontend
cmd /c npm run dev
```

访问：`http://127.0.0.1:5173`。

## CLI 规则挖掘

```powershell
python app.py --input data.csv
```

可选参数：`--target`、`--segment-field`、`--output-dir`。

## 唯一全流程验收命令

```powershell
python scripts/full_flow_acceptance.py
```

该脚本执行全量后端回归、中文映射扫描、前端构建、Git 检查、密钥扫描和智谱默认绑定检查，结果写入 `test_artifacts/full_flow/latest.json`。
