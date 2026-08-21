# Model Agent Change Log

## Change #046 - Phase 3 acceptance, security, and regression evidence

- Added a repeatable 60k-row acceptance runner using the saved Phase 2 real-LLM proposals, with ignored JSON/NPZ/Registry evidence.
- Added 28 focused Feature Engine checks covering the required named cases, conditional aggregation, rule-group derivation, explicit user confirmation, API behavior, and context-cache invalidation.
- Verified strict historical windows, rebuild equality, generated-not-approved status, malicious-expression rejection, and leakage blocking.
- Verification: 114 backend tests passed; frontend production build passed; `git diff --check` passed; no dynamic formula execution primitives were found.
- Browser limitation: no controllable browser instance was available for final visual clicking; API/component behavior and production compilation were verified automatically.

## Change #045 - Feature Engine workbench and Agent integration

- Added Feature Engine navigation and Proposal/Spec, Compiled, and Generated tabs with Compile, explicit Generate confirmation, capability-gap detail, execution detail, lineage, and Rebuild controls.
- Feature Proposal cards can compile through FeatureSpec; neither Analysis Agent nor Decision Agent can execute features.
- Added the read-only feature-capability summary to Analysis context and invalidated context cache after successful generation.
- Added FeatureSpec, compile, plan, execution, capability-gap, generated-feature, and rebuild APIs.

## Change #044 - Deterministic execution, lineage, audit, and rebuild

- Added column, historical-window, entity, conditional, rule-group-derived, and composite execution through controlled AST nodes.
- Historical windows use `t-window <= event_time < t`; same-timestamp and future records are excluded.
- Added safe-divide policy, missing-policy lineage, sanity statistics, compact NPZ artifacts, execution audit, data/code versions, immutable feature versions, duplicate guard, and rebuild comparison.
- Successfully generated features remain `GENERATED`; execution never implies model or production approval.

## Change #043 - FeatureSpec, capabilities, DSL, AST, and compiler

- Added the modular `core/feature_engine` package with FeatureSpec, capability registry, proposal normalizer, controlled DSL parser, normalized AST, deterministic compiler, standardized statuses, capability gaps, and error categories.
- Unknown operators, fields, data sources, entities, windows, leakage fields, raw datetimes, and malicious expressions are rejected before execution.
- Arbitrary Python, SQL, shell, `eval`, `exec`, subprocess execution, and dynamic import of proposal formulas are not supported.

## Change #038 - Phase 1 final runtime acceptance

- 目标：以真实 Provider、Mock、多 Agent、多 Binding、SSE、审计和全量回归完成 Phase 1 验收。
- 修改：无新增运行逻辑；记录最终验收证据与现场限制。
- 原因：真实 LLM Smoke 不得由 Mock 或静态测试代替，失败尝试也必须如实留痕。
- 影响模块：Agent Chat Runtime、Binding、Trace、测试与构建。
- 文件：`CHANGELOG_AGENT.md`。
- 测试：真实智谱 `glm-4-plus` General/Analysis/Decision 三 Agent PASS；General 精确返回 `AGENT_CHAT_CONNECTED`；Prompt 分别为 `general_v1`、`analysis_agent_v1`、`decision_agent_v1`；真实 SSE `start/delta/done` PASS；真实/Mock Binding 历史隔离 PASS；全量 `pytest` 79 passed；`npm run build` PASS；Python compile PASS。
- 结果：Phase 1 后端、构建和结构验收通过；真实调用均为 `runtime_type=LLM`，Trace 含 Provider/Binding/Model/Prompt/Latency/Tokens/Call ID；Mock 调用明确为 `MOCK`。
- 已知问题：当前 Codex 会话没有可连接浏览器实例，鼠标滚轮、触控板和视觉 Drawer 现场测试未执行；已由 CSS 高度链与状态逻辑自动测试覆盖，但不能替代最终人工演示。开发模式 `uvicorn --reload` 在受限执行环境中无法访问外网，真实 Smoke 使用无热重载单进程 uvicorn 完成。

## Change #037 - Phase 1 deterministic failure identity and acceptance naming

- 目标：保证“没有实际 Provider 调用”的失败也有合法 Runtime 标识，并让验收测试名称与 Phase 1 清单一一对应。
- 修改：无 Binding 的本地校验失败标记为 `DETERMINISTIC`；测试改名为 `test_no_binding_no_mock_fallback`、`test_switch_binding_history`、`test_switch_agent_history`；滚动结构断言扩展到侧栏、Drawer、Streaming 会话隔离和 near-bottom 条件。
- 原因：失败前没有选中 Provider 时不得误标成 LLM，验收证据需要可直接检索。
- 影响模块：Agent Chat Service、Phase 1 tests。
- 文件：`backend/app/services/agent_chat_service.py`、`tests/test_llm_chat_v11.py`。
- 测试：全量 pytest 79 passed；npm build PASS；Python compile PASS。
- 结果：通过。
- 已知问题：无浏览器实例，滚轮/触控板现场测试仍未执行。

## Change #036 - Phase 1 Chat acceptance regression coverage

- 目标：把 Runtime、Trace、切换历史、无 Mock 回退、Stop、Retry、错误呈现和滚动结构固化为回归测试。
- 修改：更新密钥掩码断言；新增三 Agent Prompt、逐消息 runtime/trace、Binding/Agent 历史、取消保留内容与审计、Retry 不覆盖原消息、错误映射及 CSS 高度链断言。
- 原因：Phase 1 的稳定性要求必须由自动化证据覆盖，不能只依赖人工页面观察。
- 影响模块：Agent Chat 后端与前端结构验收。
- 文件：`tests/test_llm_chat_v11.py`。
- 测试：待执行 Chat 定向测试、全量 pytest 与 npm build。
- 结果：测试已编写，待运行。
- 已知问题：滚轮/触控板仍需要可用浏览器实例做最终现场测试。

## Change #035 - Phase 1 Chat scroll layout and message-level controls

- 目标：让消息区成为唯一主滚动容器，并完成智能滚底、逐消息 Trace、三 Agent/Model 分离、Stop/Retry 与友好错误交互。
- 修改：重建 Chat 高度链为 `100vh → flex(min-height:0) → chat-main → chat-messages`；Header/Composer 固定；消息区独立 `overflow-y:auto`；增加 120px near-bottom 判断与“Back to bottom”；切会话会取消旧 Stream；Trace 按 Message 打开；Agent 收敛为 General/Analysis/Decision；Binding 仅列有效项；新增真实 Retry 调用、Rename、Zhipu 选项与密钥掩码展示。
- 原因：原 Grid 子项按内容最小高度撑开，`.messages` 没有形成真实滚动框；无脑 `scrollIntoView` 会强制打断历史阅读。
- 影响模块：Agent Chat 页面、布局 CSS、前端 API Client。
- 文件：`frontend/src/pages/AgentChatPage.tsx`、`frontend/src/agent-chat.css`、`frontend/src/api/client.ts`、`backend/app/services/agent_chat_service.py`。
- 测试：待 TypeScript build、后端测试、结构断言与浏览器 smoke。
- 结果：实现完成，用户上翻后停止自动跟随，点击按钮恢复跟随。
- 修正：首次 TypeScript 编译发现 Binding 动态字段对象少一个闭合括号，已立即修复并重新进入构建验证。
- 已知问题：当前会话没有可连接浏览器实例，真实鼠标滚轮现场测试待环境恢复后执行。

## Change #034 - Phase 1 streaming audit and cancellation persistence

- 目标：让同步/流式调用共享真实 Runtime 标识、错误元数据和可追溯取消状态。
- 修改：审计统一写入 `runtime_type`；流式消息逐块保存已生成内容；Stop 立即标记 `CANCELLED`，随后保存 Trace；流式成功补存 token usage；失败调用保留选定 Binding/Provider/Model/Prompt。
- 原因：Mock 不得伪装成 LLM，用户停止后内容不得消失，Provider 失败也必须可审计。
- 影响模块：Agent Chat Service、SQLite Message/Call Log。
- 文件：`backend/app/services/agent_chat_service.py`。
- 测试：待补充 runtime、trace、cancel、error、retry 与切换历史测试。
- 结果：后端实现完成，待自动化与真实 API 验收。
- 已知问题：Provider 不返回 usage 时继续保存 `NULL`，前端应显示 N/A。

## Change #033 - Phase 1 runtime identity and three-mode contract

- 目标：收敛 Agent Chat 为 General / Analysis / Decision 三个只读入口，并让每次真实或测试调用可被明确审计。
- 修改：新增 `ANALYSIS_AGENT` 与 `DECISION_AGENT` 独立 Prompt；Agent 公共类型收敛为三个 Mode；Message 与 LLM Call 增加可迁移的 `runtime_type` 字段；Binding API 恢复密钥掩码，禁止完整回显。
- 原因：Agent 决定任务与 Prompt，Binding 决定 Provider/Model；`LLM`、`MOCK`、`DETERMINISTIC` 必须真实可辨识，密钥不得出现在响应中。
- 影响模块：LLM Schema、Prompt Registry、Binding Store、Chat SQLite Schema。
- 文件：`core/llm/schemas.py`、`core/llm/prompts.py`、`core/llm/bindings.py`、`core/llm/storage.py`。
- 测试：待本阶段后端回归、真实 LLM Smoke 与前端构建统一验收。
- 结果：代码结构已完成，待后续步骤验证。
- 已知问题：旧五类内部 Prompt 继续保留用于兼容既有记录，但不再作为前端用户入口。

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
## Change #042 - Phase 2 real Zhipu acceptance and structured JSON compatibility

- Target: complete real-data, real-provider acceptance and close issues discovered during the run.
- Changes: added a secret-free acceptance runner; requested provider JSON-object mode; safely unwraps Markdown JSON fences before Pydantic validation while retaining the single repair limit.
- Reason: Zhipu returned valid structured content inside a Markdown code fence, which the strict parser previously rejected after repair.
- Modules: LLM runtime, provider acceptance, regression coverage.
- Files: `core/llm/runtime.py`, `scripts/phase2_real_acceptance.py`, `tests/test_context_phase2.py`.
- Tests: real `glm-4-plus` call over the large mineable dataset plus focused parser tests.
- Result: 3 hypotheses, 4 feature proposals, 7 pending human proposals, 5,889 estimated context tokens; all five acceptance gates passed.
- Known issues: provider/network latency is external; the acceptance artifact remains under ignored `test_artifacts/phase2_acceptance`.

## Change #041 - Analysis Workbench context and proposal UI

- Target: expose Context Preview, structured Analysis output, proposal review and context-level trace fields in the existing Chat Workbench.
- Changes: added source switches, field focus, token budget, preview item counts/source counts; rendered findings and hypotheses as sections; added Save Hypothesis / Save Feature Proposal / Reject controls and validation badges; extended Trace with Context ID/Hash/count/tokens/sources.
- Reason: Phase 2 evidence and proposals must be inspectable and human-gated rather than hidden in raw JSON.
- Modules: frontend Agent Chat, API client, styles.
- Files: `frontend/src/pages/AgentChatPage.tsx`, `frontend/src/api/client.ts`, `frontend/src/agent-chat.css`.
- Tests: TypeScript and Vite production build.
- Result: build passed; existing Phase 1 chat controls remain available.
- Known issues: Vite native-config and bundle-size warnings remain non-blocking.

## Change #040 - Structured Analysis Agent and proposal safety guards

- Target: make Analysis Agent output machine-valid and keep every generated object in proposal-only state.
- Changes: added Pydantic Analysis schemas and deterministic proposal extraction; added invalid-source, duplicate-feature/hypothesis, leakage and raw-datetime guards; saved accepted objects as `PROPOSED` only; limited recent runtime history to eight messages; added context metadata to message/call audit storage.
- Reason: LLM output cannot directly mutate feature execution, experiments or models and must preserve evidence/audit lineage.
- Modules: LLM schemas/prompts/runtime, Chat service/storage/API, Feature/Hypothesis Registry bridge.
- Files: `core/llm/schemas.py`, `core/llm/prompts.py`, `core/llm/provider.py`, `core/llm/storage.py`, `backend/app/services/agent_chat_service.py`, `backend/app/api/agent_chat.py`.
- Tests: structured mock flow, proposal guards, Phase 1 compatibility and full regression suite.
- Result: structured outputs validate; blocked proposals cannot be saved; accepted Phase 2 records remain `PROPOSED` with no feature execution or training.
- Known issues: none found in local regression.

## Change #039 - Deterministic modular Context Builder

- Target: replace character truncation with a NEW-only, deterministic, budgeted context pipeline.
- Changes: added unified ContextRequest/ContextItem/ContextBundle schemas; modular collection, compression, ranking, deduplication, stable serialization, soft token budgeting, source-aware top-K and source-state cache invalidation; added build/get/preview APIs and durable ignored context artifacts.
- Reason: raw character slicing could break JSON, leak excessive detail and allow long conversations or registries to explode prompt size.
- Modules: Context Builder, dataset/registry/conversation sources, FastAPI context service/router.
- Files: `core/context/*`, `backend/app/services/context_service.py`, `backend/app/api/context.py`, `backend/app/main.py`, `tests/test_context_phase2.py`.
- Tests: 100 items per source explosion test, NEW/OLD isolation, cache/preview API, valid JSON and 8,000-token enforcement.
- Result: deterministic context remains valid JSON and within budget; raw data rows and OLD rule evidence are excluded.
- Known issues: token estimation is intentionally conservative and dependency-free rather than provider-tokenizer exact.
