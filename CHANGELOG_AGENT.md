# Model Agent Change Log

## Change #032 - Local Zhipu default binding and plaintext display

- Added `ZHIPU_OPENAI_COMPATIBLE` with the official OpenAI-compatible API base URL.
- Binding responses now expose the in-process API key in plaintext for the local frontend workbench, as explicitly requested.
- API keys remain absent from SQLite and Git-tracked configuration; a backend restart clears the in-process secret.

## Change #030 - Repository secret-scan hygiene

- Replaced fake test secrets that used a production-key-like prefix with neutral test-only values.
- Secret persistence and masking assertions are unchanged.
- Repository key-pattern scan now has zero matches outside ignored runtime artifacts.

## Change #029 - V1.1 final acceptance

- LLM Runtime, secret-safe multi-Provider Bindings, Agent Chat, SSE, Audit/Trace and human-gated Proposal flows are complete.
- Automated backend result: 72 passed; existing V0/V1 suites remain green.
- Frontend TypeScript/Vite production build: passed.
- Multi-Binding and Agent/Prompt switching: passed with explicit Mock bindings in isolated tests.
- REAL_LLM_SMOKE_TEST = NOT_RUN; reason: no API key reference or active real Provider Binding is configured in this environment.
- No Mock or deterministic response is reported as a real LLM call.

## Change #028 - Agent defaults, Binding usage statistics and read-only Tool audit

- Added per-Agent default Binding persistence and Auto Router precedence: Agent Default → global default/priority → enabled.
- Added Binding usage statistics for calls, success rate, average latency, total tokens and last used.
- Recorded Context Builder reads as summarized read-only tool calls on Messages without storing sensitive full results.
- The tool surface contains no train/delete/governance/experiment/rollback operations.

## Change #027 - Frontend runtime target alignment

- Updated the TypeScript target/library from ES2020 to ES2021 for the Chat workbench's standard string APIs.
- Verification: production build rerun follows.

## Change #026 - V1.1 ChatGPT-style Agent Chat Workbench

- Added primary Agent Chat navigation and a three-pane conversation/chat/trace workspace in the existing design language.
- Added conversation search/history grouping, Agent and Binding selectors, Dataset context attachment, SSE rendering, Stop, Retry, Copy and explicit execution labels.
- Added trace details for Provider/Binding/Model/Prompt/latency/tokens/context/router/error and human-gated Proposal cards.
- Added secret-safe Model Binding management with real Test Connection, enable/disable and delete actions.
- UI never labels Mock as LLM and displays `No active LLM binding configured` when no Binding exists.

## Change #025 - Chat persistence decode and SSE retry-lineage fix

- Prevented double JSON decoding when newly inserted SQLite rows already contain in-memory dictionaries/lists.
- Added `parent_message_id` support to the SSE path so retry versions retain lineage without changing the original answer.
- Verification: focused V1.1 suite rerun follows.

## Change #024 - V1.1 LLM and Agent Chat regression suite

- Added required Binding secret, masked response, real connection path, Mock chat/stream, Runtime, Prompt Version and normalized error tests.
- Added invalid structured JSON plus one-repair validation coverage.
- Added HTTP conversation/message persistence, SSE, multi-Binding switch, Agent switch, Audit/Trace and Proposal create/accept/reject tests.
- Added explicit no-binding/no-fake-response and configured fallback attribution tests.

## Change #023 - Explicit fallback audit and Feature Proposal execution

- Added configured-only fallback Binding support; no cross-provider fallback occurs unless `fallback_binding_id` is set.
- Fallback traces explicitly record the failed primary Binding, normalized failure type and actual fallback Binding used.
- Hypothesis answers now create separate human-gated Hypothesis and Feature Candidate proposal cards.
- Accept writes the corresponding Registry object with source-message lineage; Reject remains non-mutating.
- Improved Mock repair behavior so invalid structured output can be repaired once under the same Agent prompt.

## Change #022 - V1.1 Conversation, SSE, Audit, Context and Proposal backend

- Added concurrent-safe SQLite persistence for conversations, messages, LLM calls, prompt versions and Agent proposals.
- Added compressed/privacy-safe Context Builder with item/character budgets and context hashes; raw business rows are not audited.
- Added General/structured Chat APIs, SSE streaming, cancellation, retry lineage, Agent/Binding switching and normalized failure persistence.
- Added complete LLM trace fields including actual Agent, Provider, Binding, Model, Prompt Version, latency, tokens, execution mode and router reason.
- Added human-only Proposal accept/reject flow; accepted Hypothesis proposals write Registry, rejected proposals never do.

## Change #021 - V1.1 LLM Runtime, Provider, Binding and Prompt foundation

- Added unified LLM Provider abstraction with OpenAI, DeepSeek, Qwen-compatible, custom OpenAI-compatible and explicit Mock bindings.
- Added secret-safe Binding metadata storage: SQLite stores only `key_ref`; request API keys remain session-only and responses are masked.
- Added real provider connection testing, normalized provider errors, chat/stream methods and no silent Mock fallback.
- Added versioned Prompt Registry plus structured Semantic/Hypothesis/Planner/Diagnosis validation and one repair attempt.
- Added runtime mode attribution (`LLM` or `MOCK`) and Auto Router decision reasons.

## Change #020 - Strict JSON persistence at the source

- Added a shared core JSON sanitizer used by API responses and analytical persistence.
- Model Agent State, State Snapshots, all JSON Registries, and legacy analysis state now write with `allow_nan=False`.
- NaN/Infinity are converted to `null` before reaching disk, preventing invalid JSON from being reloaded later.
- Added a regression assertion that persisted state contains neither `NaN` nor `Infinity` literals.

## Change #019 - Non-finite HTTP regression coverage

- Added HTTP assertions for nested NaN and Infinity in Model Agent state responses.
- Added an old dataset-summary endpoint case whose target mean is NaN and must serialize as JSON `null`.
- Removed superseded local NumPy/pandas sanitizer imports.
- Verification: focused and full suites follow.

## Change #018 - Global strict JSON finite-value response guard

- Added `SafeJSONResponse` as the FastAPI default response class for every JSON endpoint.
- Recursively converts NaN, positive/negative Infinity, NumPy scalars/arrays, pandas NA, timestamps, dates, paths, sets, and tuples to standards-compliant JSON values.
- Reused the same canonical sanitizer in Model Agent services instead of maintaining a partial local implementation.
- Prevents Starlette `ValueError: Out of range float values are not JSON compliant` even when an older analysis endpoint returns a nested NaN.

## Change #017 - Windows backend import-path startup fix

- Made `backend/run.py` independent of the shell's current working directory.
- Uvicorn supervisor and reload child now resolve `backend.app.main:app` from the repository root.
- Added a functional `python -m backend.app` entry point and updated README startup commands.
- Fixes `ModuleNotFoundError: No module named 'backend'` when starting from the backend directory.

## Change #016 - Final V1.0 verification

- Full Python suite: 46 passed.
- Model Agent HTTP end-to-end flow: passed.
- Synthetic A-H large regression: 8/8 passed with raw data and artifacts preserved locally.
- Frontend TypeScript/Vite production build: passed.
- Git diff whitespace check and tracked-source credential scan: passed; sensitive runtime/test/model outputs remain ignored.
- Remaining warnings are non-blocking dependency/build advisories (physical-core detection, LightGBM feature-name warning, TestClient deprecation, and frontend bundle-size advisory).

## Change #015 - Model Agent HTTP end-to-end regression

- Added a FastAPI TestClient flow for initial modeling, JSON-safe summary/feature reads, production-feature approval, registry side effects, and Markdown report download.
- Uses a temporary Model Agent artifact root and leaves the existing rule-analysis service unchanged.
- Verification: included in the final full-suite run.

## Change #014 - Regression acceptance semantics and metric labels

- Corrected scenario F to verify its stated goal (positive OOT AUC gain) independently from Pareto acceptance.
- Preserved the stricter experiment rejection caused by a marginally excessive KS regression, demonstrating correct guard behavior.
- Corrected UI/report metric keys for `train_oot_auc_gap` and `lift_at_10`.
- Verification: full A-H rerun and frontend build follow.

## Change #013 - LightGBM Unicode path compatibility

- Fixed native LightGBM text-model persistence on Windows projects whose absolute path contains Chinese characters.
- The booster now writes to an ASCII system temporary directory and is copied safely into the dataset-scoped model directory.
- Joblib pipeline persistence remains unchanged.
- Verification: discovered by the large regression harness; rerun follows.

## Change #012 - Standalone regression script bootstrap

- Added the repository root to the regression script import path and made its default artifact path absolute to the project.
- Allows `python scripts/model_agent_v1_regression.py` to run directly from the repository root.
- Verification: standalone harness rerun below.

## Change #011 - A-H large synthetic regression harness

- Added reproducible raw datasets and real model executions for stable LR, nonlinear LightGBM, overfitting, drift, leakage isolation, ratio gain, rejected ablation, and failed-experiment rollback.
- The harness preserves CSV inputs, models, registries, snapshots, JSON results, and a Markdown report under ignored `test_artifacts/model_agent_v1*` directories.
- Verification: execution result is recorded in the generated report.

## Change #010 - Registry timestamp-aware assertion

- Updated the hypothesis-registry test to compare persisted business fields while allowing the registry to add its audit timestamp.
- Verification: requirement suite rerun below.

## Change #009 - Exact representative rule lineage

- Ordered each rule-group feature's source rule IDs with the representative first.
- Ensures `representative` feature rebuild reproduces the originally generated values exactly.
- Verification: exact rebuild assertion added to the requirement suite.

## Change #008 - Rule-group features and governed ablation

- Added traceable representative, union, and hit-count features derived from existing NEW rule groups.
- Added exact rule-group rebuild support using persisted rule-hit masks.
- Added non-mutating feature-ablation evaluation; permanent removal remains human-gated.
- Added documented LightGBM parameter aliases for feature/bagging fractions and L1/L2 regularization.
- Verification: covered in the V1 requirement and regression suites below.

## Change #007 - Semantic artifact serialization fix

- Recursively normalized semantic artifact dictionary keys, timestamps, NumPy scalars, and non-finite floats before JSON persistence.
- Fixed initialization failure when datetime value-count samples produced `Timestamp` dictionary keys.
- Verification: reproduced with the V1 synthetic time-series dataset; full rerun follows.

## Change #006 - V1.0 Model Experiment Workbench UI

- Added the Model Experiment navigation entry and a dedicated NEW-only Agent page.
- Added controls for initialization, next experiment, one round, stop, rollback, approval decisions, and report export.
- Added model comparison, version pointers, hypothesis/feature boards, experiment audit table, diagnosis, approval queue, timeline, and detail drawer.
- Repaired legacy mojibake in the application shell while preserving all V0.7 workflow pages.
- Verification: pending TypeScript production build and browser smoke test.

## Change #001

时间：2026-08-20

目标：建立 Model Agent V1 可恢复状态与核心 Registry。

修改内容：新增 ModelAgentState、StateSnapshot、CURRENT/BEST/LAST_STABLE 指针、回滚能力，以及 Hypothesis、Feature、Experiment、Diagnosis、Approval JSON Registry。

原因：模型实验必须保留完整历史和 lineage，禁止只保存当前模型。

影响模块：Model Agent State、Registry。

新增 / 修改文件：`core/model_agent/__init__.py`、`config.py`、`state.py`、`registry.py`、`tests/test_model_agent_state.py`。

测试：新增 State Snapshot、Best/Stable、Rollback、Registry 和重复实验测试。

结果：待本轮测试验证。

已知问题：尚未接入 Semantic、Feature、Model 和 API。

## Change #002

时间：2026-08-20

目标：完成 Semantic、Hypothesis、Feature Lineage 与 Cheap Validation 基础链路。

修改内容：新增语义域识别与 LOW confidence guard；基于证据生成 Hypothesis；Feature Registry 保存机器公式和人类解释并支持精确 rebuild；计算 IV、PSI、Pearson、Spearman、Lift、Novelty，输出 PROMISING/EXPLORATORY/REJECTED/REVIEW；建立 LR/LGBM 独立 Feature Pool。

原因：所有自动特征必须有证据、可追溯、可重建，并先通过低成本验证。

影响模块：Semantic Agent、Hypothesis Agent、Feature Generator、Cheap Validation、Feature Pool。

新增 / 修改文件：`semantic.py`、`hypothesis.py`、`features.py`、`validation.py`、`tests/test_model_agent_features.py`。

测试：新增 schema、低置信语义 guard、Hypothesis Registry、公式 lineage、feature rebuild、novelty 与 feature pool 测试。

结果：待本轮测试验证。

已知问题：尚未接入模型训练、Experiment、Diagnosis 与 Orchestrator。

## Change #003

时间：2026-08-20

目标：建立 LR/LightGBM 基线、统一 Evaluator、Experiment 与 Diagnosis/Rollback。

修改内容：新增时间切分、LR L2 和保守 LightGBM 训练；统一计算 DEV/OOT AUC、KS、Lift@5/10/20、AUC Gap、Score PSI；通过配置化 Hard Gate 与 Pareto 判断 ACCEPT/REJECT；新增诊断与实验拒绝自动回滚。

原因：Champion/Challenger 不能依据训练 AUC，失败实验不能继续叠加。

影响模块：Model Training、Evaluator、Experiment Registry、Diagnosis、Rollback。

新增 / 修改文件：`models.py`、`evaluation.py`、`diagnosis.py`、`experiments.py`、`tests/test_model_agent_models.py`、`requirements.txt`。

测试：新增 LR/LGBM baseline、Evaluator accept/reject、Overfitting/Drift Diagnosis、Experiment rollback 和 duplicate experiment 测试。

结果：待本轮测试验证。

已知问题：尚未实现 Planner、Agent Loop、Human Approval、API/UI 和完整 Mock 回归。

## Change #004

时间：2026-08-20

目标：完成 Planner、有限 Agent Loop、Stop Conditions 与 Human Approval。

修改内容：Planner 按数据/泄漏/假设/漂移/诊断优先级选择单一实验；最大 3 轮、连续两轮无改善、预算、人审等条件可停止；新增强制人审动作与决策记录；Orchestrator 固定 NEW、target7、is_old 口径，按语义到 baseline 再到实验编排。

原因：V1 是有限自治研究 Agent，不是无限 AutoML。

影响模块：Planner、Agent Loop、Human Approval、Model Agent Orchestrator。

新增 / 修改文件：`planner.py`、`approval.py`、`orchestrator.py`、`tests/test_model_agent_planner.py`。

测试：新增 Planner priority、max rounds、连续拒绝停止和 Human Approval 流程测试。

结果：待本轮测试和 Mock 回归验证。

已知问题：API/UI 和 Model Agent Mock Dataset 尚未完成。

## Change #005 - Model Agent API and audit-safe persistence

- Added dataset-scoped Model Agent service and `/api/model-agent` endpoints for initialization, experiments, stop, rollback, state, registries, timeline, approvals, and report export.
- Added finite-value/NumPy JSON normalization to prevent FastAPI response serialization failures.
- Made manual rollback an auditable `ROLLBACK` experiment and connected approval decisions to feature-registry status changes.
- Added model report generation and corrected the initial CURRENT/LAST_STABLE pointer to the selected champion baseline.
- Verification: pending full API and regression test run.
## Change #031 - External browser localhost compatibility

- Fixed external-browser access on Windows systems where `localhost` resolves to IPv6 `::1` while the development services listen on IPv4.
- Pinned the Vite development server to `127.0.0.1:5173` with strict port handling.
- Made frontend API and download URLs resolve through the browser host and normalize `localhost` to `127.0.0.1`.
