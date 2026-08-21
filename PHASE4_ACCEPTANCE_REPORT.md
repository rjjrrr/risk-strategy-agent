# Risk Strategy Agent Phase 4 Acceptance Report

1. Cheap Validation 架构：`core/feature_validation/` 独立实现 schema、distribution、IV、PSI、correlation、novelty、eligibility、validator、ranking 与 audit；输入限定 NEW、Feature Artifact、target7、时间字段及现有 Feature Pool。
2. Metrics 列表：row/valid/missing/unique、数值分位数或类别 Top Values、Bad Rate Pattern、Lift、IV、PSI、月度稳定性、Pearson/Spearman、最大现有特征相关性、Novelty、inf/outlier/rare/high-cardinality 警告。
3. Validation Decision：只输出 `PROMISING / EXPLORATORY / REVIEW / REJECTED`，不生成 0–100 总分；严重泄漏、原始日期、ID-like、极低有效率、常量或严重方向翻转会拒绝。
4. LR / LGBM Eligibility：分别输出布尔值与原因；LR 强调稳定、可解释、IV 与冗余，LGBM 允许非单调、弱单变量及相关候选，但禁止泄漏、极端漂移、无效值、日期和 ID。
5. Counterfactual 设计：`core/counterfactual/` 固定模型类型、时间 DEV/OOT、seed、preprocessing 和 params；FEATURE_ADD 仅 `P → P+F`，FEATURE_REMOVE 仅 `P → P-F`。
6. Same Split 验证：Before/After 共享同一 `split_id/split_hash`，`consistency_checks.same_split=true`；存在申请时间时不会退化成随机切分。
7. Same Params 验证：Before/After 共享同一 `model_params_hash`、seed 和 preprocessing version，`same_params/same_seed=true`；实验阶段不调参。
8. Feature Marginal Gain：按 LR、LGBM 分开保存 ΔOOT AUC、ΔOOT KS、ΔLift@5/10/20、ΔAUC Gap、ΔScore PSI、ΔFeature Count，不做跨模型平均。
9. Feature Credit：保存 performance/stability/simplicity、drift/cost penalty、overall direction、confidence、experiment count；技术训练失败不写 NEGATIVE Credit。
10. Hypothesis Credit：聚合 tested/positive/neutral/negative Feature 和最佳 ΔAUC/KS/Lift10，支持 PROPOSED/TESTING/SUPPORTED/PARTIALLY_SUPPORTED/REJECTED/INCONCLUSIVE。
11. Ablation 能力：支持 LR/LGBM FEATURE_REMOVE；若移除几乎无影响，标记 Simplification Candidate 并创建待人工审批的 `REMOVE_FEATURE_PROPOSAL`，不会自动永久删除。
12. Positive Case：真实 Phase 2 Proposal `device_risk_weighted_score` 在 60k 数据上 Validation=`PROMISING`；LGBM Counterfactual=`POSITIVE/HIGH`。
13. Exploratory LGBM Case：构造稳定交互信号，Cheap Validation=`EXPLORATORY`，LR=`NEUTRAL`，LightGBM=`POSITIVE`，由真实 Python LR/LGBM 训练得到。
14. Unstable Case：DEV 上升而 OOT 下降或 AUC Gap/Score PSI 明显恶化时返回 `UNSTABLE`，不会误判 POSITIVE。
15. Redundant Case：与现有池 Spearman 相关性 >=0.95 时 Novelty=`LOW`，Validation=`REVIEW`；无边际收益时 Counterfactual 为 NEUTRAL/NEGATIVE。
16. Drift Case：PSI >=0.25 标记 `EXTREME_DRIFT`，Validation 为 REVIEW/REJECTED，默认不进入 LR。
17. Hypothesis Supported Case：3 个 Feature 中 2 POSITIVE、1 NEUTRAL，Hypothesis=`SUPPORTED`。
18. Hypothesis Rejected Case：3 个 Feature 全部 NEGATIVE/UNSTABLE，Hypothesis=`REJECTED`。
19. API：新增 `POST/GET /api/feature-validation/{feature_id}`、`POST /api/counterfactual/feature/{feature_id}`、`GET /api/counterfactual/experiments/{id}`、`GET /api/features/{id}/credit`、`GET /api/hypotheses/{id}/credit`；实验要求明确 `user_confirmed=true`。
20. 前端结果：Feature Engine 展示 Validation 指标/Decision/Eligibility、LR/LGBM Test、Ablation、实验 Preview、Before/After/Delta、Same Split/Params、Feature Credit、Hypothesis Credit 与 Timeline 数据。
21. pytest：`140 passed`；Phase 4 专项 26 项全部通过，旧 V0/V0.7/Model Agent/Phase 1/2/3 回归保持通过；仅有依赖弃用、CPU 探测和 LightGBM feature-name 警告。
22. npm build：TypeScript + Vite 生产构建通过；仅保留 Vite config loader 和大 bundle 的非阻断警告。
23. CHANGELOG：已追加 Change #047–#050，覆盖 Cheap Validation、Counterfactual、Evaluator、Feature/Hypothesis Credit、UI、Context 与真实验收。
24. 当前限制：V1 默认每个 Feature 每种模型/动作一次固定 seed 实验；未做 Bootstrap、自动调参、Group Counterfactual UI、LangGraph、Surrogate、Bandit、自动 Decision Loop 或生产 Feature Approval；现场浏览器点击仍依赖可控浏览器实例。

真实数据结果：

- Validation: `PROMISING`，valid rate 100%，Lift 2.1177，IV 0.1583，PSI 0.000077，Novelty HIGH。
- LGBM OOT AUC: 0.5975 → 0.6315，Δ +0.0340。
- LGBM OOT KS: 0.1601 → 0.2145，Δ +0.0545。
- LGBM Lift@10: 1.9079 → 2.1748，Δ +0.2668。
- AUC Gap 改善 0.0110；Score PSI 仅增加 0.00014。
- Feature Credit: Performance POSITIVE、Stability NEUTRAL、Drift LOW、Overall POSITIVE、Confidence HIGH。

可重复命令：

```powershell
python scripts/phase4_acceptance.py
python -m pytest -q
cd frontend
cmd /c npm run build
cd ..
git diff --check
```

运行证据保存在 `test_artifacts/phase4_acceptance/latest.json`，原始数据、模型和运行 Artifact 均由 `.gitignore` 排除。
