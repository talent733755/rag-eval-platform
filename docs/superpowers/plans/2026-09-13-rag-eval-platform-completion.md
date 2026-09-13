# RAG Eval Platform 后续完整交付实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Each task is intentionally small enough to review and commit independently; keep the checkbox state in this document updated as work lands.

**Goal:** 在现有项目基础、文档导入/解析 API、持久化解析 Worker 核心和管理后台壳的基础上，完成 RAG Eval Platform 的第一个可公开使用 MVP：可靠的异步文档处理、可追溯候选评测集、审核发布、HTTP/Python Adapter、可恢复实验、分阶段指标、Trace/失败诊断，以及可复现的开源交付。

**Architecture:** PostgreSQL 是任务状态、租约、版本、候选集、Adapter、实验、指标和 Trace 的事实来源；Redis 只用于唤醒提示和短时协调，Redis 不可用时数据库轮询仍能完成任务。API、Worker、Web 是独立进程。所有跨模块数据通过版本化的 Pydantic/TypeScript 公共契约连接。文档、候选集、Adapter、模型配置、实验参数、指标规则和 Trace 都保存不可变快照或明确的版本引用，从而保证结果可以回溯和重跑。外部模型调用默认关闭，只有显式配置且通过 URL、密钥和网络安全校验后才允许执行。

**Tech Stack:** pnpm workspace, Next.js, TypeScript, generated OpenAPI client, Vitest, Playwright, Python 3.12+, FastAPI, Pydantic, SQLAlchemy async, Alembic, PostgreSQL, Redis, Docker Compose, pytest, Ruff, mypy, ShellCheck, GitHub Actions.

## 当前基线与执行约束

## 本轮执行记录（2026-09-13）

已完成并分别提交：

- Worker 独立运行时、readiness、租约续期、维护入口、Compose 服务和集成门禁：`a14bcc5`、`787de91`；
- 候选生成 v1 契约、确定性 FakeProvider、安全 Provider Transport 和能力检查入口：`8cbf849`、`8acf7d3`、`47bc0ae`；
- 文档批量上传、归档引用保护、Documents 页面和客户端测试：`3c56424`、`7fe3ab5`；
- 候选评测集版本表、租户边界查询、审核/发布/归档 API 和评测集页面：`27537be`；
- `adapter-v1` 契约及受限 HTTP Adapter：`54b46d4`、`d7e7d00`；
- 可复现检索指标纯函数和 Trace v1/失败分类基础：`5fa4802`、`d2a6fda`；
- 开源协作、安全、变更记录和契约索引文档。

本轮验证结果：`make lint`、`make typecheck`、`make test` 和 `make build` 均通过；API 非集成测试为 219 passed、2 skipped。`make test-integration` 已执行迁移和基础设施启动，但 Worker 镜像构建阶段受 Docker Hub 对 pinned Python manifest 返回 403 影响，尚未完成真实容器链路验证。

明确未完成项：候选生成尚未实现数据库持久化和候选 Worker；Adapter 尚未接入 CRUD/配置快照和 Python entry point；实验执行器、模型 Provider 快照、指标持久化、Trace/失败数据库、回归集、Dashboard、生产认证和完整 E2E 仍待实现。当前没有使用假数据掩盖这些缺口。

实施分支为 `.worktrees/mvp-foundation-admin-shell`，分支名为 `codex/mvp-foundation-admin-shell`。截至 `16676f3`，以下能力已经存在并通过现有质量门禁：

- 组织、项目、成员角色、权限和审计基础；
- PDF、DOCX、Markdown、TXT 的安全上传、BlobStore、解析器注册表和资源限制；
- 文档/版本查询、显式新版本上传、解析重试、任务查询和取消；
- Blob 对账基础；
- PostgreSQL 任务抢占、租约、fencing token、attempt 历史、失败分类、崩溃恢复和不可变 chunk 持久化；
- `make lint`、`make typecheck`、`make test`、`make build` 以及当前 PostgreSQL 集成测试已通过。

计划中所有新功能遵循 TDD 顺序：先写失败测试，再实现最小逻辑，再运行针对性检查，最后运行受影响模块的完整检查。每个任务完成后使用中文提交注释，提交前不得把 `.env`、真实密钥、构建产物、测试用户数据或本机路径带入版本库。除非用户另行授权，本计划只在当前工作树本地提交，不直接推送远程仓库。

## 完成顺序与依赖

```text
Worker 运行时 ─┬─> 候选生成与评测集版本 ─> 审核/发布
               └─> Documents 页面

Adapter 契约与模型服务 ─> 实验执行器 ─> 指标计算 ─> Trace/失败诊断
评测集发布 ──────────────┘

上述后端闭环 ─> Dashboard/各业务页面 ─> E2E/部署验证
所有模块 ────> 安全、文档、CI、许可证和发布检查
```

执行顺序固定为：

1. Task 1–3：先把 Worker 运行时、批处理、心跳、Redis hint 和 Compose 可运行性补齐。
2. Task 4–6：实现候选生成契约、可配置 Provider 和评测集版本/审核 API。
3. Task 7–8：完成文档 API 的批量上传/归档，并把 Documents 页面接入真实 API。
4. Task 9–11：实现 Adapter、模型服务和可恢复实验执行器。
5. Task 12–14：实现指标、Trace、失败案例及其页面。
6. Task 15–17：完成 Dashboard、项目成员/系统设置和全链路 E2E。
7. Task 18：完成安全、许可证、发布和开源交付验收。

Task 1–8 可以作为“文档到候选评测集”里程碑；Task 9–14 作为“实验与诊断”里程碑；Task 15–18 才能标记为完整 MVP。没有 Provider 配置时，候选生成必须诚实返回 `provider_not_configured`，不得用假数据伪装功能完成。

## Task 1：完成独立 Worker 进程和配置契约

**Files:** `apps/api/src/rag_eval_api/config.py`, `apps/api/src/rag_eval_api/worker.py`, `apps/api/src/rag_eval_api/services/worker.py`, `apps/api/src/rag_eval_api/services/ingestion_jobs.py`, `apps/api/tests/test_worker.py`, `apps/api/tests/test_worker_runtime.py`, `.env.example`, `README.md`

- [ ] **Step 1: 先定义运行时失败测试。**

在 `apps/api/tests/test_worker_runtime.py` 增加以下测试：

```python
def test_worker_once_processes_at_most_configured_batch(): ...
def test_worker_heartbeat_extends_only_matching_fencing_token(): ...
def test_worker_shutdown_cancels_poll_and_closes_resources(): ...
def test_worker_writes_readiness_file_only_after_database_probe(): ...
def test_worker_requeues_expired_job_and_never_overwrites_new_owner(): ...
```

测试要求固定批次上限、租约续期的 owner/fencing 条件、SIGTERM 取消行为、数据库不可用时不写 ready 文件，以及旧 Worker 在 fencing 失败时不提交结果。运行 `uv run --directory apps/api pytest -q tests/test_worker_runtime.py`，预期新测试在实现前失败。

- [ ] **Step 2: 扩展配置并保持校验边界。**

在 `config.py` 增加并校验：`worker_poll_interval_seconds`（`0.1–60`）、`worker_heartbeat_interval_seconds`（大于 0 且小于 lease 时长）、`worker_readiness_file`（绝对路径）、`orphan_blob_grace_seconds`（不小于 3600）、`worker_redis_hint_channel`（非空）、`worker_enabled`。配置别名分别使用大写环境变量，默认值适合本地 Compose；生产环境禁止使用 development secret。`.env.example` 同步说明所有配置及“不配置 Provider 时候选生成会返回错误”的行为。

- [ ] **Step 3: 给服务层增加可取消心跳。**

在 `services/worker.py` 提取 `heartbeat(job_id, lease_id, fencing_token) -> bool`、`process_batch(limit: int) -> WorkerBatchResult` 和 `run_maintenance() -> MaintenanceResult`。解析外部任务期间由独立 asyncio task 按配置续租；心跳失败通过结构化日志和取消事件终止处理。数据库更新必须继续带 `job_id + lease_id + fencing_token` 条件，取消、超时、版本已失效和 Blob 缺失分别映射到稳定错误码。

- [ ] **Step 4: 实现 CLI 进程。**

在 `apps/api/src/rag_eval_api/worker.py` 提供 `python -m rag_eval_api.worker`，支持 `--once`、`--poll-interval` 和 `--readiness-file`。启动顺序为：加载配置 → 创建 DB/Redis/BlobStore/ParserRegistry → 执行一次数据库探针 → 写 readiness 文件 → 进入有界轮询。轮询只把 Redis pub/sub 或 list 消息当作立即唤醒提示，始终调用 PostgreSQL claim；没有 hint 也必须轮询。处理 SIGINT/SIGTERM 后停止接收新任务、取消当前可取消操作、关闭 Redis/DB/BlobStore，最后删除本进程生成的 readiness 文件。

- [ ] **Step 5: 增加维护任务。**

`run_maintenance()` 按固定周期执行过期租约恢复和 `reconcile_orphaned_blobs()`；对账 grace period 使用配置值，不能删除仍被已提交版本引用的 Blob。每个维护周期输出处理数量、失败数量和耗时字段，禁止 `print` 或吞异常。

- [ ] **Step 6: 运行 Worker 验证并提交。**

运行：

```bash
uv run --directory apps/api pytest -q tests/test_worker.py tests/test_worker_runtime.py
uv run --directory apps/api ruff check src tests
uv run --directory apps/api mypy src
python -m compileall apps/api/src/rag_eval_api
```

预期：Worker 单元/运行时测试通过，Ruff/mypy/compileall 无错误。提交：`git commit -m "feat: 完善持久化解析worker运行时"`。

## Task 2：把 Worker 接入 Compose、健康检查和 PostgreSQL 端到端测试

**Files:** `docker-compose.yml`, `docker/api.Dockerfile`, `scripts/wait-for-services.sh`, `scripts/check-worker-ready.sh`, `.github/workflows/ci.yml`, `apps/api/tests/test_worker_integration.py`, `docs/architecture/document-ingestion.md`, `docs/contracts/document-ingestion-v1.md`, `README.md`

- [ ] **Step 1: 先写集成测试。**

在 `test_worker_integration.py` 使用真实 PostgreSQL 和真实 `LocalBlobStore` 覆盖：上传文件后 Worker 进程完成 queued→processing→succeeded、解析失败保留 attempt/error、取消任务不产生 chunk、租约过期后只能由新 fencing token 完成、两个 Worker 并发时每个 job 只完成一次、不同 organization 不能互相 claim。默认无 PostgreSQL 时使用既有 marker skip，CI 集成 job 必须显式启动数据库。

- [ ] **Step 2: 增加 Compose worker 服务。**

在 `docker-compose.yml` 增加 `worker` 服务，复用 API 镜像但执行 `python -m rag_eval_api.worker`，依赖 PostgreSQL/Redis 的 healthcheck；worker 使用独立 `worker-readiness` 命名卷，把 readiness 文件挂载到 `scripts/check-worker-ready.sh` 可读位置。API 仍只运行 Uvicorn，不能在 API 进程中隐式启动 Worker。

- [ ] **Step 3: 增加健康检查和启动说明。**

`check-worker-ready.sh` 只能验证文件存在、更新时间不超过 lease 的两倍，并在失败时返回非零；不得通过删除任意目录来“修复”状态。`wait-for-services.sh` 增加可选 worker readiness 检查。README 写明 `docker compose up --build` 后 API、Web、Worker 的职责和诊断命令。

- [ ] **Step 4: 在 CI 中执行真实链路。**

`.github/workflows/ci.yml` 的 integration job 启动 PostgreSQL/Redis，执行 Alembic upgrade，启动 worker，运行 `pytest -m integration` 和 worker readiness 检查；任务结束收集 API/Worker 日志。Playwright job 使用 Compose 服务，不得依赖本机残留容器。

- [ ] **Step 5: 运行并提交。**

运行：

```bash
docker compose config
docker compose up -d postgres redis api worker web
scripts/wait-for-services.sh --include-worker
make test-integration
docker compose down
```

预期：Compose 配置通过，worker ready，端到端集成测试通过，停止服务不删除命名卷。提交：`git commit -m "feat: 接入解析worker容器运行时"`。

## Task 3：实现版本化候选生成契约和确定性测试 Provider

**Files:** `apps/api/src/rag_eval_api/candidates/protocol.py`, `apps/api/src/rag_eval_api/candidates/schemas.py`, `apps/api/src/rag_eval_api/candidates/errors.py`, `apps/api/src/rag_eval_api/candidates/fake.py`, `apps/api/src/rag_eval_api/candidates/__init__.py`, `apps/api/tests/test_candidate_protocol.py`, `docs/contracts/candidate-generation-v1.md`

- [ ] **Step 1: 先写公共契约测试。**

测试 `CandidateGenerator.generate(request, cancel_token) -> CandidateGenerationResult` 的输入输出校验：请求必须包含明确 `document_version_id`、不可变 chunk hash 列表、dataset 名称、`capability_version`、prompt/check 版本、seed/randomness 和 request id；结果中的每条候选必须包含 question、question_type、reference_answer、source version、至少一个合法 chunk evidence、automatic_checks 和 provenance。缺字段、跨版本证据、重复 ordinal、超长文本和未知 question type 必须抛稳定错误。

- [ ] **Step 2: 定义协议和错误。**

协议层只依赖 Pydantic 模型，不依赖 OpenAI SDK、LangChain 或特定数据库。定义 `CandidateGenerationRequest`、`CandidateEvidence`、`CandidateItemDraft`、`CandidateGenerationResult`、`UsageSnapshot` 和 `GenerationFailure(code, retryable, safe_message)`。`capability_version` 使用 `candidate-generation-v1`，schema version 单独保存，后续版本只能新增兼容协议或明确迁移。

- [ ] **Step 3: 实现确定性 FakeProvider。**

FakeProvider 只用于测试和 development fixture，按 seed 对传入 chunk 做确定性选择；它必须明确标记 `provider_name=fake-test`，不能成为 production 默认 Provider，也不能在用户未配置真实 Provider 时由 API 自动使用。增加相同 request snapshot 产生相同 JSON/hash 的测试。

- [ ] **Step 4: 文档化契约。**

`docs/contracts/candidate-generation-v1.md` 写明请求、响应、错误码、版本字段、证据定位、取消语义、Provider 未配置行为、发送给模型服务的数据范围和兼容策略，并加入一个只使用本地 fixture 的最小示例。

- [ ] **Step 5: 验证并提交。**

运行 `uv run --directory apps/api pytest -q tests/test_candidate_protocol.py` 和 `uv run --directory apps/api ruff check src tests`。预期所有 schema/确定性测试通过。提交：`git commit -m "feat: 定义候选生成公共契约"`。

## Task 4：实现安全的 OpenAI-compatible Provider 与候选生成服务

**Files:** `apps/api/src/rag_eval_api/candidates/provider.py`, `apps/api/src/rag_eval_api/candidates/transport.py`, `apps/api/src/rag_eval_api/services/candidate_generation.py`, `apps/api/src/rag_eval_api/services/redaction.py`, `apps/api/src/rag_eval_api/config.py`, `apps/api/tests/test_candidate_provider.py`, `apps/api/tests/test_candidate_generation.py`, `docs/security/model-provider.md`

- [ ] **Step 1: 先写外部调用安全测试。**

覆盖 HTTPS 生产限制、开发环境 HTTP 白名单、精确 host/port allowlist、用户名/密码/URL userinfo 拒绝、解析后私有/环回/链路本地 IP 拒绝、禁止跨协议重定向、连接/读取/总超时、retryable 状态码、取消请求、API key 不出现在日志/异常/数据库快照。使用 fake DNS/resolver 和 `httpx.MockTransport`，不访问真实外网。

- [ ] **Step 2: 实现受限 Transport。**

`transport.py` 在请求前解析并校验 URL，固定 `https`（development 才可使用配置白名单中的 `http`），验证解析出的每个地址，禁用自动重定向，设置 connect/read/write/pool/total timeout。响应体大小和 JSON 深度设上限；错误只返回脱敏的 provider code、HTTP 状态和 request id。API key 使用 `SecretStr` 或安全配置注入，不写入 `CandidateGenerationConfig.environment`。

- [ ] **Step 3: 实现 Provider。**

`provider.py` 只实现 OpenAI-compatible chat/completions 的最小 JSON schema 请求，不引入厂商 SDK。要求服务端响应可被 `CandidateGenerationResult` 严格校验；解析失败、schema 不合法、空候选、证据不存在和 usage 不可解析分别分类。重试只针对明确的连接错误、429 和 5xx，并使用有上限的指数退避；取消和 4xx 不重试。

- [ ] **Step 4: 实现服务层快照。**

`candidate_generation.py` 读取已完成解析的明确版本和 chunk 快照，计算排序后的 `chunk_content_hashes`，构建不可变 `CandidateGenerationConfig`，调用 Provider，事务性写入 candidate items/evidence 和审计事件。相同 `Idempotency-Key + project + document_version + dataset` 返回相同任务/结果；请求配置变化必须生成新 request id，禁止覆盖旧快照。

- [ ] **Step 5: 处理 Provider 未配置和失败。**

没有合法 Provider 配置时返回错误码 `provider_not_configured`（HTTP 503，稳定 JSON error shape），不创建候选、不写成功状态；模型超时、schema 错误和额度错误保留失败分类与可重试标记。服务层必须支持取消 token，并在取消后释放 HTTP client。

- [ ] **Step 6: 运行安全验证并提交。**

运行：

```bash
uv run --directory apps/api pytest -q tests/test_candidate_provider.py tests/test_candidate_generation.py
uv run --directory apps/api ruff check src tests
uv run --directory apps/api mypy src
```

预期：所有 SSRF、脱敏、超时、取消、幂等和严格 schema 测试通过。提交：`git commit -m "feat: 增加安全的候选生成provider"`。

## Task 5：完成候选生成 API、评测集版本和审核发布后端

**Files:** `apps/api/src/rag_eval_api/models/candidates.py`, `apps/api/alembic/versions/0004_candidate_dataset_versions.py`, `apps/api/alembic/versions/0005_candidate_generation_jobs.py`, `apps/api/src/rag_eval_api/schemas/candidates.py`, `apps/api/src/rag_eval_api/routes/candidates.py`, `apps/api/src/rag_eval_api/services/candidate_datasets.py`, `apps/api/tests/test_candidates.py`, `apps/api/tests/test_candidates_integration.py`, `docs/contracts/candidate-generation-v1.md`

- [ ] **Step 1: 先写 API 和事务约束测试。**

在 `test_candidates.py` 覆盖：解析成功版本才可生成、显式版本不可被 latest pointer 替换、无 `Idempotency-Key` 拒绝生成、重复 key 返回同一 generation job、跨项目/组织 ID 返回 404、候选详情包含来源 chunk 定位、人工修改产生审计、已发布版本不可原地修改。集成测试验证并发生成只有一份配置/一组 items，外键阻止孤儿 evidence，发布时所有 item 必须 accepted。

- [ ] **Step 2: 增加数据库模型和迁移。**

`0004_candidate_dataset_versions.py` 增加 `candidate_dataset_versions`，字段为 tenant identity、dataset_id、version_number、status、item_count、source_snapshot_hash、published_at、created_by，并使用 `(dataset_id, version_number)` 唯一约束和 tenant 复合外键。`CandidateDatasetItem` 改为归属明确的 dataset version；保留生成配置指向 dataset/version 的关系。`0005_candidate_generation_jobs.py` 增加 queued/processing/succeeded/failed/cancelled 状态、idempotency key、lease、attempt、error code 和 config snapshot 引用，并为重试保留历史。

- [ ] **Step 3: 实现候选 API。**

提供：

```text
POST /api/projects/{project_id}/documents/{document_id}/generate-candidates
GET  /api/projects/{project_id}/candidate-datasets
GET  /api/projects/{project_id}/candidate-datasets/{dataset_id}
GET  /api/projects/{project_id}/candidate-datasets/{dataset_id}/versions
GET  /api/projects/{project_id}/candidate-datasets/{dataset_id}/versions/{version_id}/items
POST /api/projects/{project_id}/candidate-datasets/{dataset_id}/versions/{version_id}/review
POST /api/projects/{project_id}/candidate-datasets/{dataset_id}/versions/{version_id}/publish
POST /api/projects/{project_id}/candidate-datasets/{dataset_id}/versions/{version_id}/archive
```

生成请求体必须包含 `document_version_id`、dataset name、generation config snapshot 和 `capability_version`；不得默认为最新版本。所有列表使用既有 opaque cursor 约定。审核接口一次只接受明确 item id、review status、comment，批量操作也必须逐条执行检查并逐条审计。

- [ ] **Step 4: 接入 Worker 队列。**

生成 API 只创建 generation job 并发布 Redis hint；候选 Provider 调用由独立 Worker 类型执行，复用 PostgreSQL lease/fencing/cancellation 模式。解析 Worker 和候选 Worker 必须使用不同 job kind，批次上限和并发上限分别配置。

- [ ] **Step 5: 生成客户端并验证。**

运行 API OpenAPI 导出/客户端生成命令，确认 `apps/web/src/lib/api/generated.ts` 只包含契约变化；运行 `uv run --directory apps/api pytest -q tests/test_candidates.py tests/test_candidates_integration.py`、`make typecheck`。提交：`git commit -m "feat: 完成候选评测集审核发布接口"`。

## Task 6：完成文档 API 的归档、引用保护和批量上传

**Files:** `apps/api/src/rag_eval_api/models/documents.py`, `apps/api/alembic/versions/0006_document_archive.py`, `apps/api/src/rag_eval_api/schemas/ingestion.py`, `apps/api/src/rag_eval_api/routes/documents.py`, `apps/api/src/rag_eval_api/services/blob_reconciliation.py`, `apps/api/tests/test_documents.py`, `apps/api/tests/test_documents_integration.py`, `docs/contracts/document-ingestion-v1.md`

- [ ] **Step 1: 先写文档生命周期测试。**

覆盖：编辑者可归档、viewer 不可归档、归档文档不可创建新版本或生成候选、已发布 dataset version 引用时未确认请求返回 409、带确认才允许归档、历史版本和候选 evidence 仍可读取、归档后 Blob 进入 grace period 而不是立即删除、跨组织访问不泄露资源存在性。并发归档/新版本上传必须只有一个事务成功改变生命周期。

- [ ] **Step 2: 实现归档 API。**

使用 `POST /api/projects/{project_id}/documents/{document_id}/archive`，请求体 `{ "confirm_referenced": boolean }`；只做软归档并记录 `archived_at/archived_by`。若有已发布评测集引用且确认值为 false，返回 `document_referenced_by_published_dataset`；成功归档写审计。历史 Blob 由对账任务按 grace period 清理，不能破坏历史数据。

- [ ] **Step 3: 实现批量上传 API。**

提供 `POST /api/projects/{project_id}/documents:batchUpload`，接受 multipart `files` 和可选的每文件 `client_id`。一次最多 `MAX_BATCH_FILES`，单文件沿用 MIME、魔数、大小、文件名和 Blob 清理校验。响应是每文件独立的 `accepted|duplicate|rejected` 结果，部分失败返回 207；客户端重试用 `Idempotency-Key` 和文件 fingerprint 保证不重复创建文档/版本。

- [ ] **Step 4: 更新文档契约和客户端。**

记录归档、批量结果、207、错误码和数据保留规则到 `document-ingestion-v1.md`，重新生成 OpenAPI client。运行 `uv run --directory apps/api pytest -q tests/test_documents.py tests/test_documents_integration.py` 和 `make lint`。提交：`git commit -m "feat: 完成文档批量上传与归档保护"`。

## Task 7：接入 Web API 客户端和 Documents 页面

**Files:** `apps/web/src/lib/api/client.ts`, `apps/web/src/lib/api/generated.ts`, `apps/web/src/lib/documents/types.ts`, `apps/web/src/lib/documents/reducer.ts`, `apps/web/src/components/documents/document-summary.tsx`, `apps/web/src/components/documents/document-filters.tsx`, `apps/web/src/components/documents/document-table.tsx`, `apps/web/src/components/documents/document-upload-dialog.tsx`, `apps/web/src/components/documents/document-detail-drawer.tsx`, `apps/web/src/components/documents/ingestion-job-status.tsx`, `apps/web/src/app/(app)/documents/page.tsx`, `apps/web/tests/documents-reducer.test.ts`, `apps/web/tests/documents-page.test.tsx`, `apps/web/tests/document-upload-dialog.test.tsx`

- [ ] **Step 1: 先写 reducer 和页面行为测试。**

测试 query string 保留 `project_id/q/type/status/cursor`，加载中/成功/空数据/网络错误/权限错误/部分批量成功状态，轮询只更新对应 job，取消后停止轮询，归档和重试后刷新当前 cursor。测试上传 reducer 的每文件状态必须独立，不能因一份失败把其他成功文件显示为失败。

- [ ] **Step 2: 扩展 typed client。**

在 `client.ts` 暴露 `listDocuments`、`getDocument`、`listDocumentVersions`、`uploadDocuments`、`archiveDocument`、`retryParse`、`cancelIngestionJob`、`generateCandidates`。multipart 上传用 `fetch` + `AbortController`，通过 `ReadableStream` 或 XHR progress adapter 报告已发送字节；不要把 API key 或完整错误响应写入浏览器日志。401/403/409/413/429/503 映射到可读的本地错误类型。

- [ ] **Step 3: 实现页面组件。**

替换 `documents/page.tsx` 的 placeholder。页面必须有统计卡（总文档、解析成功、解析中、解析失败）、搜索/类型/状态筛选、可排序且可横向滚动的表格；列包括名称、类型/大小、最新版本、解析状态/进度、关联评测集、更新时间和操作。操作按权限显示：查看详情、重试、取消、生成候选、归档。上传 dialog 支持多文件、文件校验、每文件进度、部分成功、取消和失败重试。

- [ ] **Step 4: 实现详情与版本信息。**

详情 drawer 展示文档元信息、版本列表、每个版本的 parse status/error/chunk count、任务 attempt 历史和候选引用；解析成功版本才显示生成入口，失败版本显示稳定错误码和重试入口。所有状态有文本，不只依赖颜色；动画尊重 `prefers-reduced-motion`。

- [ ] **Step 5: 验证响应式和可访问性。**

运行 `pnpm --dir apps/web test -- documents`、`pnpm --dir apps/web lint`、`pnpm --dir apps/web typecheck`。测试 viewport `320x640`、键盘 Tab/Enter/Escape、dialog focus trap、表格 header 关联、上传 input label、live region 进度和无障碍名称。提交：`git commit -m "feat: 接入文档库真实管理界面"`。

## Task 8：完成评测集审核界面和候选数据可追溯展示

**Files:** `apps/web/src/lib/api/client.ts`, `apps/web/src/components/datasets/dataset-table.tsx`, `apps/web/src/components/datasets/candidate-review-queue.tsx`, `apps/web/src/components/datasets/candidate-review-panel.tsx`, `apps/web/src/app/(app)/datasets/page.tsx`, `apps/web/src/app/(app)/review/page.tsx`, `apps/web/tests/datasets-page.test.tsx`, `apps/web/tests/review-page.test.tsx`, `apps/web/e2e/document-to-dataset.spec.ts`

- [ ] **Step 1: 先写 UI 测试。**

测试 dataset/version/item 状态、分页、加载/空/失败状态、viewer 只读、editor 可审核、admin 可发布/归档；通过、驳回、需修改、跳过使用不同确认语义，快捷键不是唯一操作。证据区域必须显示文档名、版本、page/paragraph/chunk ordinal 和 excerpt；缺失 evidence 显示错误，不显示伪造内容。

- [ ] **Step 2: 实现评测集页面。**

替换 `datasets/page.tsx` 和 `review/page.tsx` 的 placeholder，提供 dataset summary、版本选择、候选队列、详情编辑、自动检查、审计历史和发布前校验。已发布版本只能查看；修改必须创建新版本。页面将 `document_version_id` 和 candidate generation config 显式展示在 provenance 区域。

- [ ] **Step 3: 增加完整浏览器链路。**

`document-to-dataset.spec.ts` 使用测试 Provider fixture 完成上传→Worker 解析→生成候选→审核→发布；另测 Provider 未配置时显示 `provider_not_configured`，不出现候选假数据。运行 `pnpm --dir apps/web exec playwright test e2e/document-to-dataset.spec.ts`。提交：`git commit -m "feat: 完成评测集候选审核界面"`。

## Task 9：实现 Adapter 公共协议、HTTP Adapter 和 Python SDK Adapter

**Files:** `apps/api/src/rag_eval_api/adapters/protocol.py`, `apps/api/src/rag_eval_api/adapters/schemas.py`, `apps/api/src/rag_eval_api/adapters/http.py`, `apps/api/src/rag_eval_api/adapters/python_sdk.py`, `apps/api/src/rag_eval_api/adapters/registry.py`, `apps/api/src/rag_eval_api/models/adapters.py`, `apps/api/alembic/versions/0007_adapters.py`, `apps/api/src/rag_eval_api/routes/adapters.py`, `apps/api/tests/test_adapters_contract.py`, `apps/api/tests/test_http_adapter.py`, `apps/api/tests/test_python_sdk_adapter.py`, `docs/contracts/adapter-v1.md`

- [ ] **Step 1: 先写适配器契约测试。**

两种 Adapter 必须通过同一组 fixture：输入 question/reference/evidence/project context，最小响应包含 answer/citations/usage，深度响应可包含 rewritten queries、vector/keyword retrieval、merged、reranked、context 和 generation。测试缺失阶段被标为 unavailable；非法 citation、超时、取消、重试和版本变化必须有稳定错误。

- [ ] **Step 2: 定义版本化协议。**

`adapter-v1` 定义 `AdapterRequest`、`AdapterResponse`、`Citation`、`Usage`、`TraceEnvelope`、`AdapterCapability` 和错误码。Adapter 配置快照不保存明文 key；数据库字段保存 endpoint、认证引用、timeout、retry、version、trace level、enabled 和最后测试信息。公开文档给出 JSON Schema 和迁移策略。

- [ ] **Step 3: 实现 HTTP Adapter。**

复用受限 Transport 的 SSRF、重定向、DNS、大小、timeout 和脱敏策略；默认 POST JSON，content type 和 response schema 严格校验。连接测试使用合成问题且不保存真实内容；Adapter 未通过连接测试或被禁用时，实验启动返回 `adapter_unavailable`。

- [ ] **Step 4: 实现 Python SDK Adapter。**

允许用户在受控 worker 运行环境注册 entry point `rag_eval_adapter`，调用 `run(request) -> response`；限制执行超时、取消、异常边界和版本元数据。不得让 SDK 直接访问 API session 或绕过公共 schema。测试用本地 fixture package，不执行任意用户提交代码。

- [ ] **Step 5: 完成 API/UI 契约验证。**

提供 Adapter CRUD、连接测试、启用/禁用和脱敏详情接口，接入 `adapters/page.tsx`。运行 `uv run --directory apps/api pytest -q tests/test_adapters_contract.py tests/test_http_adapter.py tests/test_python_sdk_adapter.py`、`make typecheck`。提交：`git commit -m "feat: 建立统一的RAG Adapter协议"`。

## Task 10：实现模型服务配置和可复现实验快照

**Files:** `apps/api/src/rag_eval_api/models/model_providers.py`, `apps/api/alembic/versions/0008_model_providers.py`, `apps/api/src/rag_eval_api/routes/model_providers.py`, `apps/api/src/rag_eval_api/services/experiment_snapshots.py`, `apps/api/src/rag_eval_api/schemas/experiments.py`, `apps/api/tests/test_model_providers.py`, `apps/api/tests/test_experiment_snapshots.py`, `docs/contracts/experiment-v1.md`, `docs/security/model-provider.md`

- [ ] **Step 1: 先写安全和快照测试。**

测试 provider key 只从安全配置/加密存储读取，列表和日志只显示末四位或固定脱敏值；连接测试不保存用户问题；实验快照包含 dataset version、document version、Adapter version、model config version、parameters、metric rules、platform version、random seed 和 environment hash，创建后不可更新。

- [ ] **Step 2: 实现模型服务管理。**

支持 OpenAI-compatible base URL、model、service type、timeout、retry、enabled；复用 `transport.py` 的 URL 安全检查。配置变更创建新版本，旧版本可供历史实验读取但不能被删除；审计记录创建、测试、启用、禁用和失败原因。

- [ ] **Step 3: 实现实验草稿快照。**

实验创建前校验 dataset version 已发布、Adapter 可用、model provider 已启用，保存 immutable snapshot。预计样本数/超时/成本是基于明确配置计算的估算，无法估算时返回“不可用”而不是虚构数字。提交：`git commit -m "feat: 保存可复现实验与模型配置快照"`。

## Task 11：实现可恢复实验执行器和运行记录

**Files:** `apps/api/src/rag_eval_api/models/experiments.py`, `apps/api/src/rag_eval_api/models/runs.py`, `apps/api/alembic/versions/0009_experiments_and_runs.py`, `apps/api/src/rag_eval_api/services/experiments.py`, `apps/api/src/rag_eval_api/services/run_worker.py`, `apps/api/src/rag_eval_api/routes/experiments.py`, `apps/api/src/rag_eval_api/routes/runs.py`, `apps/api/tests/test_experiments.py`, `apps/api/tests/test_run_worker.py`, `apps/api/tests/test_experiments_integration.py`

- [ ] **Step 1: 先写状态机和并发测试。**

覆盖 draft→queued→running→completed/partial_failed/failed/cancelled、单样例失败不阻塞全局、取消后不启动新样例、失败样例单独重试、Worker 崩溃后租约恢复、两个 run worker 不重复执行同一样例、已启动实验快照不可修改。所有状态迁移拒绝非法跳转并写审计。

- [ ] **Step 2: 建模实验和样例运行。**

实验记录绑定 dataset version、Adapter snapshot、model snapshot、metric rule version 和参数 JSON；run item 记录 candidate item、attempt、status、started/finished、safe error、usage、latency 和 trace id。对外暴露总数、完成数、成功数、失败数、跳过数、进度、耗时、预计剩余和成本。

- [ ] **Step 3: 实现 run worker。**

复用解析 Worker 的 lease/fencing/heartbeat；每个样例独立超时、取消、有限重试和资源释放。原始 Adapter response 可按实验 trace level 保存，敏感 header/body 必须脱敏；不保存超出配置的 request content。每次重试保留历史 attempt，当前状态只由匹配 fencing token 更新。

- [ ] **Step 4: 提供 API 和页面。**

提供实验创建、启动、取消、重试失败样例、详情和运行列表接口，接入 `experiments/page.tsx`、`runs/page.tsx`。启动前展示样例数、预计耗时和成本；启动后锁定配置。提交：`git commit -m "feat: 实现实验任务与可恢复运行记录"`。

## Task 12：实现指标契约、计算器和指标看板 API

**Files:** `apps/api/src/rag_eval_api/metrics/protocol.py`, `apps/api/src/rag_eval_api/metrics/retrieval.py`, `apps/api/src/rag_eval_api/metrics/generation.py`, `apps/api/src/rag_eval_api/metrics/engineering.py`, `apps/api/src/rag_eval_api/services/metric_calculation.py`, `apps/api/src/rag_eval_api/models/metrics.py`, `apps/api/alembic/versions/0010_metrics.py`, `apps/api/src/rag_eval_api/routes/metrics.py`, `apps/api/tests/test_metrics.py`, `apps/api/tests/test_metric_contract.py`, `docs/contracts/metrics-v1.md`

- [ ] **Step 1: 先写纯函数测试。**

用固定 fixture 验证 Recall@K、Precision@K、Hit Rate、MRR、nDCG、证据命中率、父块覆盖率、多路互补率、Answer Correctness、Faithfulness、Citation Correctness、Context Precision/Recall、拒答准确率以及平均/P50/P95 延迟、token、成本、失败率、超时率。空集、缺失 trace、重复证据、并列分数和部分失败必须有定义并在契约文档中固定。

- [ ] **Step 2: 定义指标版本和结果模型。**

每个 metric plugin 有 `metric_name`、`version`、输入要求、聚合方式、缺失值策略和 provenance。结果按 experiment/run、筛选维度和 sample id 保存，原始分子/分母或分布摘要可重新计算；指标版本升级不修改历史结果。

- [ ] **Step 3: 实现计算和下钻 API。**

实验完成或手动触发时计算指标，支持按实验、问题类型、难度、文档、标签筛选，多实验对比，并返回可下钻的 sample ids。报告导出先提供稳定 JSON/CSV API，不能导出未授权项目数据。

- [ ] **Step 4: 接入 metrics 页面。**

替换 `apps/web/src/app/(app)/metrics/page.tsx` placeholder，使用统一卡片、趋势/对比图和失败样例链接；每个数值显示时间范围、样本数、实验和 metric version。提交：`git commit -m "feat: 增加分阶段指标计算与看板接口"`。

## Task 13：实现 Trace 存储、查询和失败诊断

**Files:** `apps/api/src/rag_eval_api/models/traces.py`, `apps/api/alembic/versions/0011_traces_and_failures.py`, `apps/api/src/rag_eval_api/schemas/traces.py`, `apps/api/src/rag_eval_api/services/trace_store.py`, `apps/api/src/rag_eval_api/services/failure_diagnosis.py`, `apps/api/src/rag_eval_api/routes/traces.py`, `apps/api/src/rag_eval_api/routes/failures.py`, `apps/api/tests/test_trace_store.py`, `apps/api/tests/test_failure_diagnosis.py`, `docs/contracts/trace-v1.md`

- [ ] **Step 1: 先写 Trace 完整性测试。**

测试最小 Trace 和深度 Trace 的统一 envelope、阶段顺序、阶段缺失标记、原始响应脱敏、大小上限、复制 JSON 的稳定序列化、租户隔离和授权下钻。缺失阶段必须返回 `available=false` 与原因，不得返回空数组冒充已采集。

- [ ] **Step 2: 持久化不可变 Trace。**

Trace 关联 run item、adapter snapshot、platform version、trace level 和 stage payload hash；成功写入后不原地修改。大 payload 使用 BlobStore 并只在数据库保存安全引用/摘要，查询按权限和大小分页。审计/日志不包含完整 prompt、API key 或未经允许的原始文档全文。

- [ ] **Step 3: 实现失败分类和诊断建议。**

覆盖 PRD 中的证据未召回、查询改写、向量/关键词/融合、重排、上下文、答案忠实度、引用、拒答、Adapter/超时/基础设施错误。诊断结果必须带 `is_suggestion=true`、规则版本和 evidence source；人工归类、备注、负责人、忽略、加入回归集和关闭必须产生审计。

- [ ] **Step 4: 接入 Trace/失败页面。**

替换 `traces/page.tsx` 和 `failures/page.tsx`，实现阶段展开/收起、原始文本、标准证据标记、失败阶段、同类失败跳转、Trace JSON 复制、Adapter 原始响应和缺失阶段提示。提交：`git commit -m "feat: 完成Trace存储与失败诊断"`。

## Task 14：实现失败案例到回归集的闭环

**Files:** `apps/api/src/rag_eval_api/models/regression_cases.py`, `apps/api/alembic/versions/0012_regression_cases.py`, `apps/api/src/rag_eval_api/routes/regression_cases.py`, `apps/api/src/rag_eval_api/services/regression_cases.py`, `apps/api/tests/test_regression_cases.py`, `apps/web/src/components/failures/regression-case-dialog.tsx`, `apps/web/tests/failure-regression.test.tsx`, `docs/contracts/regression-v1.md`

- [ ] **Step 1: 先写引用和版本测试。**

加入回归集必须保留原 failure、run item、candidate item、dataset version 和 trace id；源数据归档后仍能读取；重复加入幂等；只有有权限的 editor/admin 可操作；忽略/关闭/重新打开状态迁移有审计。

- [ ] **Step 2: 实现回归案例模型/API。**

提供失败案例查询、分类、备注、负责人、加入回归集、忽略、恢复和关闭接口，所有查询支持 project/原因/状态/负责人筛选。回归集可作为下一次实验的明确输入，不复制并漂移原始候选内容。

- [ ] **Step 3: 接入失败页面并测试。**

在 `failures/page.tsx` 增加操作 dialog、历史实验表现和回归集状态，运行 API/Web 单测。提交：`git commit -m "feat: 建立失败案例回归闭环"`。

## Task 15：完成 Dashboard、项目成员和系统设置

**Files:** `apps/api/src/rag_eval_api/routes/dashboard.py`, `apps/api/src/rag_eval_api/routes/settings.py`, `apps/api/src/rag_eval_api/routes/members.py`, `apps/api/tests/test_dashboard.py`, `apps/api/tests/test_settings.py`, `apps/api/tests/test_members.py`, `apps/web/src/app/(app)/page.tsx`, `apps/web/src/app/(app)/settings/members/page.tsx`, `apps/web/src/app/(app)/settings/system/page.tsx`, `apps/web/tests/dashboard.test.tsx`, `apps/web/tests/members.test.tsx`, `apps/web/tests/settings.test.tsx`

- [ ] **Step 1: 先写权限和聚合测试。**

Dashboard 所有 KPI 必须限定当前 project、时间范围、样本数和实验；成员邀请/改角色/移除只允许 admin，viewer 只读；系统设置有项目覆盖、校验范围、审计和默认值回退。跨组织和归档项目不得泄漏数据。

- [ ] **Step 2: 实现 API 聚合。**

提供文档、候选集、待审核、最近实验、质量趋势、最近失败和快捷入口所需的聚合接口；查询必须使用有界时间范围、分页或汇总 SQL，不能加载全量样本到 Web 进程。设置 API 复用现有 Settings 校验并区分 secret 字段。

- [ ] **Step 3: 完成页面和状态。**

Dashboard 指标标注时间范围/样本数/实验，失败原因可跳转 Trace；成员页支持邀请、角色变更、移除确认和活动审计；系统设置显示生效配置来源。提交：`git commit -m "feat: 完成工作台与管理设置"`。

## Task 16：补齐认证、权限和敏感数据治理

**Files:** `apps/api/src/rag_eval_api/auth/`, `apps/api/src/rag_eval_api/models/user.py`, `apps/api/alembic/versions/0013_authentication.py`, `apps/api/src/rag_eval_api/middleware.py`, `apps/api/tests/test_authentication.py`, `apps/api/tests/test_security_regressions.py`, `apps/web/src/lib/auth/session.ts`, `apps/web/src/components/layout/user-menu.tsx`, `docs/security/authentication.md`, `.env.example`

- [ ] **Step 1: 先写安全回归测试。**

覆盖未认证请求、过期 session、CSRF/Origin 校验、登录失败限速、密码或 OIDC session 不写日志、tenant/project RBAC、归档资源访问、路径穿越、恶意文件签名、SSRF、超大请求、CORS 和安全响应头。测试 fixture 中使用伪造 key，且断言日志与响应中不存在完整 secret。

- [ ] **Step 2: 实现最小可替换认证。**

本地开发提供明确的 development-only fixture actor；生产要求 OIDC 或安全 session 配置，拒绝默认 development secret。认证上下文继续向下游提供 actor/org/project，所有变更记录登录、成员、文档、候选集、Adapter、模型服务、实验和系统设置审计。

- [ ] **Step 3: 完成隐私说明。**

`docs/security/authentication.md` 和 `docs/security/model-provider.md` 说明哪些文档片段、问题、答案、Trace 会发送到外部 Provider，默认不外传，日志/保留/删除行为和管理员配置。提交：`git commit -m "feat: 加固认证权限与敏感数据治理"`。

## Task 17：建立全链路 E2E、可观测性和部署验证

**Files:** `apps/web/e2e/document-to-dataset.spec.ts`, `apps/web/e2e/experiment-to-trace.spec.ts`, `apps/web/e2e/permissions.spec.ts`, `scripts/seed-e2e-data.sh`, `scripts/check-compose.sh`, `docker-compose.yml`, `.github/workflows/ci.yml`, `apps/api/src/rag_eval_api/observability.py`, `apps/api/tests/test_observability.py`, `docs/operations/runbook.md`

- [ ] **Step 1: 先写 E2E 场景和可复现 fixture。**

使用 deterministic FakeProvider/FakeAdapter fixture，覆盖上传→解析→失败/重试→候选→审核→发布→创建实验→运行→指标→Trace→失败案例→回归集；覆盖取消、部分批量上传、viewer/editor/admin、Redis 不可用时 DB poll、Worker 重启恢复。fixture 不包含业务真实材料。

- [ ] **Step 2: 加结构化观测。**

统一 request id、job id、attempt、lease id、fencing token、trace id、project id、error code 字段；日志按 JSON 输出并做 secret/redaction filter。API、Worker、Provider、Adapter、实验和指标记录耗时/结果计数；健康端点区分 liveness、readiness、数据库、Redis hint 可用性和 Worker ready。

- [ ] **Step 3: 加 Compose 和 Playwright 检查。**

`check-compose.sh` 从干净命名项目启动服务，等待全部 healthcheck，执行 migration/seed、Playwright 和 API smoke，最后仅停止本次命名项目。Playwright 至少运行 desktop、320px、keyboard/reduced-motion 三组检查。CI 保存失败截图、视频、API/Worker 日志和数据库 migration 输出。

- [ ] **Step 4: 编写运维手册并验证。**

`runbook.md` 记录启动/停止、迁移、Worker 卡住、租约恢复、Blob 对账、Redis 不可用、数据库备份恢复、日志字段、数据保留和升级回滚。运行 `bash scripts/check-compose.sh` 和 `pnpm --dir apps/web exec playwright test`。提交：`git commit -m "test: 增加全链路部署与浏览器验证"`。

## Task 18：完成开源发布、依赖审计和最终验收

**Files:** `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md`, `LICENSE`, `.github/ISSUE_TEMPLATE/bug-report.yml`, `.github/ISSUE_TEMPLATE/feature-request.yml`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `README.md`, `docs/operations/release.md`, `docs/contracts/README.md`, `docs/architecture/README.md`, `Makefile`, `package.json`

- [ ] **Step 1: 补齐公开协作文件。**

`CONTRIBUTING.md` 说明环境、分支、中文提交注释、迁移规范、OpenAPI/client 生成、测试和 PR 清单；`CODE_OF_CONDUCT.md` 使用公开可复用文本并写报告渠道；`SECURITY.md` 写漏洞报告范围、支持版本和不应提交的秘密；`CHANGELOG.md` 记录每个版本的新增、修复、破坏性变更和迁移。

- [ ] **Step 2: 审计依赖和许可证。**

锁定 Python/Node/Docker 依赖版本，执行 `uv export --directory apps/api --format requirements-txt`、`pnpm licenses list` 或仓库已选许可证工具、`pip-audit`、`pnpm audit --prod`；对无法说明用途、许可证或维护状态的依赖禁止合入。将审计命令和允许的例外记录到 `docs/operations/release.md`，不把扫描 token 写入 CI。

- [ ] **Step 3: 固化契约与迁移策略。**

`docs/contracts/README.md` 索引 document-ingestion-v1、candidate-generation-v1、adapter-v1、experiment-v1、metrics-v1、trace-v1、regression-v1，说明 OpenAPI 生成方式、向后兼容期限、破坏性变更迁移和数据库 migration 顺序。`docs/architecture/README.md` 链接模块边界、任务租约、数据追溯和安全边界。

- [ ] **Step 4: 加发布工作流。**

`release.yml` 只从受保护 tag 触发，先运行全部质量门禁和 Compose smoke，再构建可复现 API/Web 镜像，生成 SBOM，校验镜像不包含 `.env`/secret/测试数据，最后生成 changelog artifact。发布版本与 platform version 写入实验、Trace 和报告快照。

- [ ] **Step 5: 执行最终质量门禁。**

在干净工作树和全新命名 Docker Compose 项目中运行：

```bash
uv lock --directory apps/api --check
make lint
make typecheck
make test
make test-integration
make build
bash -n scripts/*.sh
shellcheck scripts/*.sh
docker compose config
bash scripts/check-compose.sh
uv run --directory apps/api pip-audit
pnpm --dir apps/web audit --prod
pnpm --dir apps/web exec playwright test
```

预期：全部命令退出码为 0；允许的 macOS bubblewrap skip 必须在结果中明确记录，Linux CI 必须实际执行 sandbox 测试；OpenAPI 生成后 `git diff --exit-code apps/web/src/lib/api/generated.ts`；没有未提交构建产物、密钥、临时文件或本机路径。

- [ ] **Step 6: 形成交付记录。**

在 `docs/HANDOFF.md` 记录最终 commit、迁移版本、镜像 tag、质量门禁结果、已知限制和回滚命令。最后提交：`git commit -m "docs: 完成MVP开源发布准备"`。远程推送必须在用户明确确认后单独执行，并先展示待推送 commit 和远程分支。

## 跨任务质量和安全规则

每个 API 任务必须同时包含：tenant 复合约束、权限矩阵、幂等/并发行为、稳定错误码、审计事件和 OpenAPI 变更。每个 Worker 任务必须同时包含：有限批次、超时、取消、心跳、fencing、重试/恢复、结构化日志和资源关闭。每个 Web 任务必须同时包含：loading/empty/error/partial success、键盘操作、320px 布局、`prefers-reduced-motion` 和敏感错误脱敏。

下列行为在任何任务中都不得实现：使用假候选冒充 Provider 成功；在数据库中保存明文 API key；用 latest pointer 替代请求中的明确版本；用 Redis 状态替代 PostgreSQL 事实；旧租约覆盖新租约；删除被历史评测集引用的 Blob；把完整 prompt、原始文档或 Provider 响应写入普通日志；跨 tenant 返回资源存在性；跳过迁移、权限或审计以实现批量快捷路径。

## 最终验收矩阵

| 能力 | 必须可验证的结果 |
| --- | --- |
| 文档资产 | 上传单文件/批量文件，部分失败可见，版本可查询，解析可重试/取消，归档不破坏历史 |
| 异步任务 | API/Worker 独立，PostgreSQL claim，Redis 仅 hint，心跳/fencing/恢复/关闭可测试 |
| 候选评测集 | 明确文档版本，候选带 evidence/provenance，Provider 未配置时不造数据，审核后才能发布 |
| Pipeline | HTTP 与 Python SDK 共用 adapter-v1，连接测试、版本快照、超时/重试/Trace level 完整 |
| 实验 | 绑定所有快照，支持启动/取消/失败样例重试/崩溃恢复，单样例失败不静默吞掉 |
| 评测诊断 | 检索/生成/工程指标可筛选下钻，Trace 显示缺失阶段，失败可分类并进入回归集 |
| 权限安全 | 组织/项目隔离、RBAC、审计、SSRF/上传/路径/secret 防护、外部数据范围可说明 |
| 开源交付 | Compose、迁移、`.env.example`、契约、示例、CI、许可证/安全审计、发布和回滚文档齐备 |

## 执行方式

建议按 Task 1–18 分阶段执行，每完成一个任务就运行该任务的针对性测试并提交中文 commit；跨任务合并前再运行完整质量门禁。若由多个 Agent 协作，只并行处理没有共享迁移/接口依赖的任务，并由主 Agent 负责读取和解释本计划、合并冲突、运行最终验证和更新 `docs/HANDOFF.md`。
