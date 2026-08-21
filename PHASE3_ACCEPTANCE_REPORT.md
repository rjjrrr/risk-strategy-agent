# Risk Strategy Agent Phase 3 Acceptance Report

1. Phase 2 Commit: `ad62237 feat: complete phase 2 analysis context and proposals`，已在 Phase 3 开发前独立提交。
2. Feature Engine 架构: Proposal Normalizer → FeatureSpec → Capability Checker/Compiler → DSL/AST Executor → Validation → Registry/Audit → Rebuild；代码拆分于 `core/feature_engine/`。
3. FeatureSpec Schema: 包含业务意图、类型、源字段/源特征、实体、申请时间、窗口、DSL、方向、Hypothesis/Proposal、数据源、缺失策略、数据版本、Spec 版本与时间戳。
4. Capability Registry: 提供算子、窗口、实体聚合、派生特征和数据源能力摘要，并通过 `GET /api/feature-engine/capabilities` 暴露。
5. 支持 DSL Operators: ADD/SUB/MUL/SAFE_DIV/ABS/MIN/MAX/CLIP/LOG1P、缺失、普通聚合、历史窗口、实体、IF/比较/IN/BOOLEAN_AND、条件窗口及规则组派生。
6. Compiler Status 类型: `SUPPORTED_TEMPLATE`、`COMPOSABLE_DSL`、`NEEDS_NEW_OPERATOR`、`INSUFFICIENT_DATA`、`INVALID_SOURCE_FIELD`、`LEAKAGE_RISK`、`DATETIME_RAW_FORBIDDEN`、`UNSUPPORTED_ENTITY`、`UNSUPPORTED_WINDOW`、`INVALID_EXPRESSION`、`REVIEW_REQUIRED`、`DUPLICATE_FEATURE`。
7. Column Executor: 受控递归 AST 执行，覆盖列变换、条件表达式、复合表达式和默认 `MISSING` safe-divide 策略。
8. Window Executor: 使用 pandas groupby/rolling，支持 1h/6h/24h/7d/30d/90d 计数、求和、均值、去重和条件聚合。
9. Entity Executor: entity key 不写死字段名，支持 ENTITY_COUNT、ENTITY_NUNIQUE 与实体历史窗口。
10. Future Leakage Guard: 所有历史窗口严格执行 `t-window <= event_time < t`，未来和同时间戳记录均不进入当前特征。
11. Feature Lineage: Registry 保存 Spec/Proposal/Hypothesis、字段/特征/数据源、DSL/AST、机器/人工公式、计划、代码/数据版本、缺失策略、窗口/实体、Artifact 与状态。
12. Rebuild: 按 Feature Registry → FeatureSpec → ExecutionPlan 重放；数值使用 `np.allclose(equal_nan=True)`，离散值 exact match。
13. Duplicate Guard: normalized AST + 排序后源字段 + 语义含义一致时返回 `DUPLICATE_FEATURE` 和已有 Feature ID；公式变更生成新版本，不覆盖旧版本。
14. Capability Gap 机制: 明确记录缺失 operator、data source、entity support、field、原因和建议，不再笼统返回“需要特征工程”。
15. `device_risk_weighted_score`: Phase 2 真实 Proposal 编译为 `COMPOSABLE_DSL`，算子 `EQ/IF`，60,000 行执行成功，重建一致，Registry 状态 `GENERATED`。
16. `low_income_device_risk_combo`: 编译为 `COMPOSABLE_DSL`，算子 `BOOLEAN_AND/EQ/IF/LE`，60,000 行执行成功，重建一致。
17. Ratio Regression: `SAFE_DIV(query_cnt_7d,query_cnt_90d)` 为 `SUPPORTED_TEMPLATE`；60,000 行执行、Registry/Rebuild 流程通过，零分母保留 missing。
18. Window Regression: `device_apply_cnt_24h` 为 `COMPOSABLE_DSL`；结果 `[0,0,2,1,0]` 与严格历史定义一致。
19. Entity Regression: `ip_shared_user_cnt_30d` 为 `COMPOSABLE_DSL`；结果 `[0,0,2,3,0]` 与历史去重定义一致。
20. Malicious Formula Test: `__import__`、lambda、DataFrame 下标、import、open 均返回 `INVALID_EXPRESSION`，没有执行。
21. Leakage Test: `SUSPECT_LEAKAGE` 源字段返回 `LEAKAGE_RISK`；原始 datetime 数值特征返回 `DATETIME_RAW_FORBIDDEN`。
22. Rebuild Test: 同 dataset/spec/code version 重建通过 `NUMERIC_ALLCLOSE`；数据版本不一致时明确失败，不伪装复现。
23. pytest: `114 passed`，仅有依赖弃用、CPU 探测及 LightGBM feature-name 警告。
24. npm build: TypeScript + Vite 生产构建通过；保留 Vite 配置模式及大 bundle 警告。
25. git diff --check: 通过；Windows 工作区仅提示未来 LF→CRLF 转换，不存在 whitespace error。
26. CHANGELOG: 已追加 Change #043–#046，覆盖 FeatureSpec、Capability、Compiler、DSL、Executor、Lineage、Rebuild 与 Test。
27. 当前限制: Phase 3 不做自动模型实验、Cheap Validation、LangGraph 或生产审批；事件特征仍要求真实事件/关系数据源；当前没有可控浏览器实例，因此最终鼠标点击未现场执行，已由 API 测试、组件结构断言、生产构建和真实数据脚本覆盖。

可重复验收命令：

```powershell
python scripts/phase3_acceptance.py
python -m pytest -q
cd frontend
cmd /c npm run build
cd ..
git diff --check
```

最新的真实数据证据保存在 `test_artifacts/phase3_acceptance/latest.json`，该目录受 `.gitignore` 保护，不提交原始或运行期数据。
