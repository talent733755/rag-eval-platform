# RAG Eval Platform 剩余工作实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前已完成的文档解析、评测集审核基础推进为可复现、可恢复、可审计的完整 MVP，并完成开源交付门禁。

**Architecture:** PostgreSQL 是任务、版本、快照、实验、指标和 Trace 的事实来源；Redis 只做唤醒提示。API 负责权限、校验和创建不可变快照，独立 Worker 负责候选生成与实验执行，Web 只消费版本化 API。所有外部 Provider/Adapter 默认关闭，网络访问必须经过 HTTPS、allowlist、DNS、超时、重试、取消和脱敏边界。

**Tech Stack:** FastAPI、SQLAlchemy/Alembic、PostgreSQL、Redis、Pydantic、Next.js、TypeScript、Vitest、Playwright、Docker Compose、Ruff、mypy。

---

## 当前状态和执行规则

当前分支已完成 Worker、文档导入、批量上传、文档库页面、候选评测集版本审核 API、候选/Adapter/指标/Trace 的部分契约基础。未完成能力不得用假数据或 placeholder 响应伪装为可用；Provider 未配置必须返回 `provider_not_configured`。

每个任务必须按“失败测试 → 最小实现 → 受影响模块完整检查 → 中文提交”执行。提交前不得带入 `.env`、密钥、用户数据、构建产物和机器路径。Docker Hub 基础镜像 403 的集成阻塞必须保留记录，不能通过跳过集成测试掩盖。

## 文件边界

- `apps/api/src/rag_eval_api/candidates/`：候选协议、Provider 和候选生成执行逻辑，不访问 Web 或路由上下文。
- `apps/api/src/rag_eval_api/adapters/`：HTTP/Python Adapter 公共输入输出、网络/进程隔离和错误边界。
- `apps/api/src/rag_eval_api/models/`、`alembic/versions/`：租户复合键、不可变版本、任务租约和历史快照。
- `apps/api/src/rag_eval_api/services/`：幂等、快照、Worker 状态机、指标/Trace 持久化和审计。
- `apps/api/src/rag_eval_api/routes/`、`schemas/`：只做权限、输入输出和服务编排；不嵌入 Provider 业务逻辑。
- `apps/web/src/lib/api/`、`components/`、`app/(app)/`：生成客户端、状态 reducer 和页面交互；不保存密钥、不展示原始敏感响应。
- `docs/contracts/`、`docs/security/`、`docs/operations/`：公共契约、限制、迁移和运维说明。

## Task 1：完成候选生成持久化和候选 Worker

**Files:**

- Create: `apps/api/alembic/versions/0005_candidate_generation_jobs.py`
- Create/modify: `apps/api/src/rag_eval_api/models/ingestion.py`, `apps/api/src/rag_eval_api/services/candidate_generation.py`, `apps/api/src/rag_eval_api/services/candidate_worker.py`
- Modify: `apps/api/src/rag_eval_api/routes/candidates.py`, `apps/api/src/rag_eval_api/schemas/candidates.py`, `apps/api/src/rag_eval_api/worker.py`
- Test: `apps/api/tests/test_candidate_generation_service.py`, `apps/api/tests/test_candidate_worker.py`, `apps/api/tests/test_candidates_api.py`

- [x] **Step 1: 写失败测试。** 已覆盖已解析明确版本、同项目 Idempotency-Key、chunk hash 快照、Provider 未配置、候选 item/evidence 落库和 attempt/fencing 基本路径；取消/过期 lease 的专门回归仍列入后续增强。
- [x] **Step 2: 增加 generation job 持久化。** 复用 `IngestionJob` 的租约与 attempt 机制，新增 `source_version_id`、`generation_config_id`、`candidate_dataset_version_id` 及租户复合外键，迁移从 0004 升级并提供降级。
- [x] **Step 3: 实现快照服务。** 事务内校验明确版本和不可变 chunks，计算排序后的 hash，创建 `CandidateGenerationConfig`、`CandidateDataset`、`CandidateDatasetVersion` 和 generation job。
- [x] **Step 4: 实现候选 Worker。** 已实现仅 claim `generate_candidates`、Provider 结果校验、item/evidence/version 写入、heartbeat、取消和 fencing；真实 Provider runtime 已按配置接入，有限重试策略仍需在实验执行器阶段统一。
- [ ] **Step 5: 接通 API 和 OpenAPI。** 生成接口和 Web typed client 已接通，Provider 不可用返回 503 且不创建候选；数据集分页/统一错误契约和审核页面闭环归入 Task 2，需继续完成后再勾选本步。
- [ ] **Step 6: 验证并提交。** 运行候选定向测试、API 非集成测试、Ruff、mypy、Alembic offline SQL；提交 `feat: 完成候选生成持久化与worker执行`。

## Task 2：完成 Documents/评测集/审核 Web 闭环

**Files:**

- Create: `apps/web/src/lib/documents/reducer.ts`, `apps/web/src/lib/candidates/reducer.ts`, `apps/web/src/components/documents/document-detail-drawer.tsx`, `apps/web/src/components/documents/ingestion-job-status.tsx`, `apps/web/src/components/candidates/candidate-review-workspace.tsx`
- Modify: `apps/web/src/lib/api/client.ts`, `apps/web/src/app/(app)/documents/page.tsx`, `apps/web/src/app/(app)/datasets/page.tsx`, `apps/web/src/app/(app)/review/page.tsx`
- Test: `apps/web/tests/documents-reducer.test.ts`, `apps/web/tests/documents-page.test.tsx`, `apps/web/tests/candidate-review.test.tsx`

- [ ] **Step 1: 测试状态机。** 固定 project/query/type/status/cursor 保留规则、列表 loading/error/403/409/503、每文件独立批量结果、job 轮询仅更新对应行、取消停止轮询、归档/重试刷新当前 cursor。
- [x] **Step 2: 扩展 typed client。** 已增加文档详情、任务、归档、重试、取消、候选生成及评测集/version/items/review/publish 方法；统一错误信封只保留状态、错误码和安全消息。
- [ ] **Step 3: 实现文档详情和任务状态。** 展示版本号、sha256 摘要、解析状态、失败安全码、取消/重试/归档按钮；轮询使用 AbortController 和退避，组件卸载必须取消请求。
- [x] **Step 4: 实现候选审核。** `/review` 已展示问题、参考答案、来源版本和 chunk excerpt，支持逐条接受/拒绝，发布前阻止 pending，发布后禁用修改。
- [ ] **Step 5: 验证并提交。** 运行 Web lint、typecheck、Vitest、build；提交 `feat: 完成文档与候选审核web闭环`。

## Task 3：完成 Adapter 公共实现和配置管理

**Files:**

- Create: `apps/api/src/rag_eval_api/adapters/python_sdk.py`, `registry.py`, `models/adapters.py`, `routes/adapters.py`, `schemas/adapters.py`
- Create: `apps/api/alembic/versions/0006_adapters.py`
- Modify: `apps/api/src/rag_eval_api/adapters/http.py`, `apps/api/src/rag_eval_api/config.py`, Web adapters page
- Test: `apps/api/tests/test_python_sdk_adapter.py`, `test_adapters_api.py`, `apps/web/tests/adapters-page.test.tsx`

- [x] **Step 1: 写契约和隔离测试。** 已覆盖 entry point 返回协议、异常/超时/超大响应分类和不泄露凭据；版本协商和取消回归将在实验执行器统一补齐。
- [x] **Step 2: 实现 Python SDK Adapter。** 已使用 spawn 子进程加载受信任的已安装 entry point，限制执行时长、异常边界和返回体大小；不执行用户提交源码。
- [x] **Step 3: 持久化 Adapter 配置。** 已保存 endpoint、环境变量凭据引用、timeout、retry、adapter version、trace level、enabled、last_test 状态；明文 key 不进入数据库/API。
- [x] **Step 4: 增加 CRUD/连接测试 API 和页面。** 已补齐项目作用域详情、编辑、管理员删除、HTTP 合成连接测试和 `last_test_status` 持久化；Python 连接测试在未配置受信任 entry point 时明确返回 `adapter_test_unsupported`。
- [x] **Step 5: 验证并提交。** API CRUD/失败状态测试、Web API client/工作台测试、OpenAPI 重新生成已完成；实验启动前 `adapter_unavailable` 校验随 Task 4 完成。

## Task 4：完成模型服务和实验配置快照

**Files:** `apps/api/src/rag_eval_api/models/model_providers.py`, `apps/api/alembic/versions/0007_model_providers.py`, `apps/api/src/rag_eval_api/routes/model_providers.py`, `apps/api/src/rag_eval_api/services/experiment_snapshots.py`, `apps/api/src/rag_eval_api/schemas/experiments.py`, `apps/api/tests/test_model_providers.py`, `apps/api/tests/test_experiment_snapshots.py`, `docs/contracts/experiment-v1.md`

- [ ] **Step 1:** 已覆盖 provider 凭据引用缺失时的安全失败、连接测试不保存问题内容和快照环境 hash；实际 Token 只从进程环境注入，末四位展示留待接入安全凭据存储后实现。
- [x] **Step 2:** 已实现模型服务项目作用域 CRUD、受限 Transport 能力测试和不可变配置引用；真实模型调用默认关闭，URL 复用安全 Transport。
- [x] **Step 3:** 已实现独立实验草稿校验服务：dataset version 必须 published、Adapter 已启用且测试成功、Provider 已启用、参数有界、随机种子明确；返回不可运行的稳定错误码。
- [ ] **Step 4:** 模型 Provider CRUD/能力测试与快照校验已验证并分阶段提交；安全凭据末四位展示、实验实体化和启动路由仍需后续任务补齐。

## Task 5：完成可恢复实验执行器

**Files:** `apps/api/src/rag_eval_api/models/experiments.py`, `apps/api/alembic/versions/0009_experiments.py`, `apps/api/alembic/versions/0010_experiment_idempotency.py`, `apps/api/alembic/versions/0011_experiment_run_leases.py`, `apps/api/src/rag_eval_api/services/experiment_worker.py`, `apps/api/src/rag_eval_api/routes/experiments.py`, `apps/api/src/rag_eval_api/schemas/experiments.py`, `apps/api/tests/test_experiment_worker.py`, `apps/web/src/app/(app)/experiments/page.tsx`, `apps/web/src/components/experiments/experiments-workspace.tsx`

- [ ] **Step 1:** 写并发、幂等、取消、逐样例重试、租约过期、新 fencing token、成本/耗时统计测试。
- [x] **Step 2:** 已建模 experiment、run、run_item、attempt，保存配置 snapshot 和安全错误；外键带 tenant identity，Run 增加 lease/heartbeat/fencing 字段。
- [ ] **Step 3:** 已实现按样例 bounded timeout 调 Adapter、usage/latency/trace_id、单样例隔离、过期 lease 恢复和历史 attempt；有限重试、取消中断和成本统计仍需后续增强。
- [x] **Step 4:** 已提供创建/启动/取消/失败项重试/详情/列表 API 和实验进度页面；启动前展示样例数和配置选择，成本估计在 Provider 费率契约完成前保持未提供。
- [ ] **Step 5:** 验证并提交 `feat: 实现实验任务与可恢复运行记录`。

## Task 6：完成指标持久化与 Dashboard

**Files:** `apps/api/src/rag_eval_api/models/metrics.py`, `apps/api/alembic/versions/0012_metrics.py`, `apps/api/src/rag_eval_api/services/metric_calculation.py`, `apps/api/src/rag_eval_api/routes/metrics.py`, `apps/api/tests/test_metrics_api.py`, `apps/web/src/app/(app)/metrics/page.tsx`, `apps/web/src/app/(app)/page.tsx`

- [x] **Step 1:** 已补 success/failure/completion、非空答案、Trace 覆盖、延迟、Token 工程指标；检索证据不可用时显式记录 missing reason。
- [x] **Step 2:** 已建模 append-only metric definition/version/result，保存分子分母、分布摘要、sample/run/维度和 provenance；历史结果不可被新版本覆盖。
- [x] **Step 3:** 已接入完成 Run 后计算，支持幂等重算以及按 experiment/run/sample 下钻 API；检索指标待 Task 7 Trace/证据持久化后接通。
- [x] **Step 4:** 已替换 metrics/dashboard 占位页，数值展示样本数和 metric version；时间显示已标注服务端 UTC，细粒度时间范围筛选待后续 Dashboard 聚合任务。

## Task 7：完成 Trace、失败案例和回归集闭环

**Files:** `apps/api/src/rag_eval_api/models/traces.py`, `apps/api/src/rag_eval_api/models/regression_cases.py`, `apps/api/alembic/versions/0013_traces_failures.py`, `apps/api/alembic/versions/0014_regression_cases.py`, `apps/api/src/rag_eval_api/routes/traces.py`, `apps/api/src/rag_eval_api/routes/failures.py`, `apps/api/src/rag_eval_api/routes/regression_cases.py`, `apps/api/src/rag_eval_api/services/trace_persistence.py`, `apps/api/src/rag_eval_api/services/failure_cases.py`, `apps/api/src/rag_eval_api/services/regression_cases.py`, `apps/api/tests/test_trace_persistence.py`, `apps/api/tests/test_regression_cases.py`, `apps/web/src/app/(app)/traces/page.tsx`, `apps/web/src/app/(app)/failures/page.tsx`, `apps/web/src/app/(app)/review/page.tsx`, `docs/contracts/trace-v1.md`

- [x] **Step 1:** 已覆盖 Trace stage 完整性、payload hash、敏感字段脱敏、大小边界、租户字段和不可变数据库边界测试。
- [x] **Step 2:** 已持久化 Trace/Failure；过大 payload 写 BlobStore opaque 引用，查询 API 有 tenant/limit 权限边界；安全 JSON 响应已提供，导出下载待后续补强。
- [x] **Step 3:** 已将失败分类关联 run_item/run/experiment/trace，保存稳定原因、建议和 attempt；同类聚合待回归集任务一并补齐。
- [x] **Step 4:** 已建模 regression case，加入操作保留原 failure/run item/candidate/dataset version/trace 引用，重复加入幂等且有审计。
- [x] **Step 5:** 已完成 Trace、失败案例和失败页加入回归集操作；提交 `feat: 完成Trace失败与回归闭环`。

## Task 8：完成认证、设置、Dashboard 和安全治理

**Files:** auth middleware/providers, settings routes/pages, dashboard aggregation, tests, `docs/security/`, `docs/operations/runbook.md`

- [ ] **Step 1:** 补认证回归测试：未认证、过期 token、跨组织 ID、viewer/editor/admin 边界、审计事件和 CORS。
- [ ] **Step 2:** 实现可替换 OIDC/JWT boundary；development actor 仅 development 可启用，production 禁止默认 secret。
- [x] **Step 3:** 已将既有成员 API、Provider 配置 API 接入设置页；Dashboard/指标页读取真实版本化结果并覆盖空/加载/错误状态，跨租户聚合 API 和更细粒度筛选仍待补强。
- [x] **Step 4:** 已补认证边界、Provider 密钥、Trace 脱敏、数据保留和运行故障处置说明；OIDC/JWT provider 接入仍是明确缺口。

## Task 9：全链路 E2E、部署和开源发布验收

**Files:** `apps/web/e2e/document-to-dataset.spec.ts`, `experiment-to-trace.spec.ts`, `permissions.spec.ts`, `scripts/seed-e2e-data.sh`, `scripts/check-compose.sh`, observability, CI, `docs/operations/runbook.md`, `LICENSE`

- [ ] **Step 1:** 使用确定性 fixture 验证文档上传→解析→候选生成→审核发布→实验→指标→Trace→回归集；禁止外部 Provider 和真实用户数据。
- [ ] **Step 2:** 统一 request/job/attempt/lease/fencing/trace/project/error 字段，API/Worker/Provider/Adapter 结构化日志脱敏。
- [ ] **Step 3:** 使用可访问的 pinned Amazon ECR Public 官方镜像源替换 Docker Hub 后运行 Compose、迁移、Worker ready、Playwright 和 API integration；Worker ready、迁移和 API integration 已通过，Playwright 仍待在 CI/Linux 环境执行；失败上传日志但不上传 secrets。
- [x] **Step 4:** 已补 MIT LICENSE、依赖许可证清单、npm/pip 审计命令、README、CHANGELOG、Issue/PR 模板和发布检查清单；官方 npm 审计与 Python `pip-audit` 均通过。
- [x] **Step 5:** 已运行 `make lint && make typecheck && make test && make build && make test-integration` 并记录结果；本轮提交使用中文注释。

## 依赖顺序和完成定义

执行顺序为 Task 1 → Task 2 → Task 3/4 → Task 5 → Task 6 → Task 7 → Task 8 → Task 9。Task 1–2 完成后才算“文档到评测集”闭环；Task 5–7 完成后才算“实验与诊断”闭环；Task 9 完成前项目不能宣称完整 MVP。

每个任务必须有实现、异常路径测试、契约文档、受影响模块质量检查和中文提交。所有外部依赖不可用时，系统必须返回明确错误或使用数据库事实源继续工作，不能返回假成功。

## 本轮执行记录（2026-09-14）

- 已完成 Task 1 Step 1–4：候选生成快照幂等、generation job 复合引用、独立 Candidate Worker、Provider 配置接入和租约 fencing。
- 已验证：API 非集成测试 `222 passed, 2 skipped, 6 deselected`；候选/文档定向测试 `29 passed`；Web `lint`、`typecheck`、Vitest `58 passed`。
- 最新门禁：`make lint && make typecheck && make test && make build` 全部通过；API `229 passed, 2 skipped, 6 deselected`，Web `62 passed`，生产构建成功。
- 当前进行中：Task 7，重点是 Trace/失败案例持久化和回归集闭环；Task 1 的数据集分页与 Task 2 的完整状态 reducer 仍保留为后续补强项。
- 本轮新增：候选审核页面、审核 reducer、文档详情抽屉和文档/任务操作 typed client；任务轮询、重试交互、数据集分页仍未完成。
- 本轮新增：Python SDK Adapter 子进程隔离、Adapter 配置迁移/API/页面；连接测试和完整 CRUD 仍未完成。
- 本轮新增：模型 Provider 配置迁移/API 与不可变实验快照服务；实验实体、启动校验和可恢复执行器仍未完成。
- 本轮新增：文档详情任务轮询、完成/失败/取消状态、重试和取消交互；Task 2 剩余评测集分页和完整状态 reducer 仍未完成。
- 本轮新增：Adapter 项目作用域 CRUD、HTTP 合成连接测试和前端操作；实验启动前 Adapter 可用性校验仍待 Task 4。
- 本轮新增：Python Adapter trusted entry point registry 和模型 Provider CRUD/能力测试；实验实体、启动校验和模型/Adapter 完整快照引用仍待 Task 4/5。
- 本轮新增：实验/Run/RunItem/Attempt 模型、快照创建/启动校验、租约 Worker、取消/失败项重试 API 和实验页面；运行指标、Trace、成本、取消中断和完整 E2E 仍待后续任务。
- 本轮新增：`0012_metrics` 迁移、不可变 metric definition/result、Run 终态指标计算、幂等重算和三级下钻 API；metrics/dashboard 已接入真实结果，检索指标等待 Trace 证据持久化。
- 本轮验证：API 非集成测试 `260 passed, 2 skipped, 6 deselected`，ruff/mypy/format 全部通过；Web lint/typecheck/Vitest `66 passed`，生产构建成功。
- 本轮新增：`0013_traces_failures`、`0014_regression_cases` 迁移，Trace/Failure 脱敏持久化、Blob 引用、失败页和回归集幂等加入；Task 7 当前批次验证 API `244 passed, 2 skipped, 6 deselected`，Web 构建成功。
- 已知环境限制：Playwright 尚未在本机执行；Compose Worker 集成已切换到内容 digest 相同的 Amazon ECR Public 官方镜像源并通过完整 API integration 门禁。
- 本轮新增：可配置 HS256 JWT boundary，验证 Bearer token 的签名、issuer、audience、exp、nbf、UUID 身份声明和数据库 membership；完整 OIDC/JWKS、非对称密钥轮换、登录/刷新会话和撤销策略仍待后续接入。
- 本轮开源验收：补齐 MIT LICENSE、Issue/PR 模板、发布检查清单和 Web/API 依赖许可证记录；升级 Next `15.5.24`、PostCSS `8.5.28`、Sharp `0.35.4` 安全覆盖后，官方 npm audit 无已知漏洞，Python `pip-audit --skip-editable --strict --local` 无已知漏洞。
- 本轮集成回归：修复 `0005` Alembic check constraint 命名约定，并拆分 `0012/0013/0014` 的 PostgreSQL 多语句 `op.execute`；新增 `0015_schema_alignment` 对齐历史索引、租户外键和 ORM 默认值，空库迁移、`alembic check`、Worker 镜像构建/readiness 与 6 项 API integration 均通过。
