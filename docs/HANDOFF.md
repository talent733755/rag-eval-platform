# 项目接手文件

> 更新时间：2026-09-14
> 当前工作目录：`/Users/yanxs/code/ai_coding/rag-eval-platform/.worktrees/mvp-foundation-admin-shell`
> 当前分支：`codex/mvp-foundation-admin-shell`
> 当前提交：请以 `git log -1 --oneline` 为准（开发认证与可配置 JWT 边界切片）

## 1. 接续规则

下次继续工作时，先阅读本文件、根目录 `AGENTS.md`、
`docs/superpowers/plans/2026-09-10-document-ingestion-and-candidate-data.md`，再检查
`git status` 和当前提交。不要从项目历史重新推导需求，也不要把当前阶段代码当成
Demo 交付。本项目的铁律是按完整 GitHub 开源项目建设：公共契约、异常处理、测试、
安全、可观测性、许可证、CI 和文档都必须同步演进。

当前分支是独立 worktree，尚未合并回 `main`；最新提交已推送到同名远程分支。

## 2. 已完成内容

### 设计与基础设施

- MVP PRD：`docs/superpowers/specs/2026-09-09-rag-eval-platform-mvp-prd.md`
- 管理后台低保真原型：`docs/prototypes/rag-eval-admin-low-fi.html`
- UI 设计规范：`docs/design/rag-eval-platform-ui-spec.md`
- 文档摄取/候选数据实施计划：`docs/superpowers/plans/2026-09-10-document-ingestion-and-candidate-data.md`
- 文档摄取公共契约：`docs/contracts/document-ingestion-v1.md`
- 文档摄取架构：`docs/architecture/document-ingestion.md`
- 根目录 `AGENTS.md` 已记录“完整开源项目”铁律。

### 文档摄取 foundation

已完成并提交：

- tenant-scoped SQLAlchemy 模型和 Alembic 迁移：documents、document_versions、chunks、
  ingestion_jobs、attempts、leases、candidate 相关模型及租户复合约束；
- `BlobStore` protocol 和安全的 `LocalBlobStore`：私有目录、opaque storage key、
  原子发布、禁止覆盖、目录描述符、symlink 防护、大小/校验和限制；
- PDF、DOCX、Markdown、TXT parser 及 canonical chunk/source location；
- `ParserRunner` 进程边界：严格 JSON 协议、重复 key/NaN/非法 UTF-8 拒绝、输入输出硬上限、
  进程组超时清理、启动前 RLIMIT、最小环境、临时工作目录；
- strict 模式只接受完整 bwrap profile，禁止 `unshare`/`env`/额外或乱序参数；
- runtime bind 已收紧为仓库 `.venv` 和明确 root-owned Python 安装实例，校验真实路径、
  目录结构、owner、权限；空 runtime allowlist fail closed；strict child 使用 resolved
  interpreter；
- CI 已安装 bubblewrap 并包含 capability probe 和真实 strict parser 执行测试；集成测试
  Compose 环境使用临时隔离 env、清理 trap 和 per-run 数据库配置。

### 上传 API 初版

`d1db722` 新增：

- `POST /api/projects/{project_id}/documents`；
- multipart 单文件上传；扩展名/MIME/签名/空文件/大小校验；
- project editor/admin 权限；viewer 和跨项目访问拒绝；
- `Idempotency-Key` + request fingerprint；同 key 重放、冲突返回 `409`；
- 同项目同 `(sha256, byte_size)` 返回 `409 duplicate_document`；
- 创建 `Document`、首个 `DocumentVersion`、queued parse `IngestionJob`；
- 成功上传写 `document.uploaded` audit event；
- 相关测试：`apps/api/tests/test_documents_api.py`，当前 7 个测试通过。

### 上传 API 安全修复切片

已补齐上一节阻断项中的实现和回归测试：

- 应用 lifespan 默认装配并关闭 `LocalBlobStore`；测试可注入替代 BlobStore；
- ASGI receive 层在 multipart 解析前限制完整请求体，并保留路由/BlobStore 文件级限制；
- 数据库提交、完整异常和已知冲突路径都会清理已发布但未被数据库引用的 blob；
- 空文件返回 `422 validation_error`；审计只写入 `idempotency_key_sha256`；
- 新增生命周期、chunked body、提交失败清理和配置边界测试。

### 文档读取与任务 API 切片

已完成并提交：

- `GET /api/projects/{project_id}/documents`：筛选、稳定排序、opaque cursor 分页和总数摘要；
- `GET /documents/{document_id}`、`GET /documents/{document_id}/versions` 及版本详情；
- `POST /documents/{document_id}/versions/{version_id}/retry-parse`：保留旧 job，创建新的
  queued parse job，支持幂等重放和冲突拒绝；
- `GET/POST /api/projects/{project_id}/ingestion-jobs/{job_id}`（取消使用 `/cancel`）：
  项目级任务查询、取消、状态转换和审计；
- viewer 读取权限、editor 重试/取消权限，以及跨项目查询隔离回归测试。

### 显式文档版本上传切片

已完成并提交：

- `POST /api/projects/{project_id}/documents/{document_id}/versions`：为已有文档创建下一个
  immutable version，更新 `latest_version_id`，并创建 queued parse job；
- 复用上传文件校验、重复内容保护、幂等重放/冲突响应、BlobStore 资源清理和审计脱敏；
- 保留旧版本与旧任务，新增版本历史回归测试，并重新生成 OpenAPI Web client。

### 孤儿 Blob 对账基础

已完成并提交：

- `BlobStore.iter_objects()`：安全枚举已发布 opaque regular objects，跳过临时文件、非法条目和不安全目录；
- `reconcile_orphaned_blobs()`：以已提交的 `document_versions.storage_key` 为事实源，按宽限期清理旧孤儿，
  统计近期跳过、已消失对象和删除失败；
- BlobStore 与对账服务单元测试，覆盖引用保护、宽限期和失败重试计数。

### 持久化解析 Worker 核心

已完成并提交：

- `IngestionWorker.run_once()`：使用 PostgreSQL 行锁领取 queued parse job，创建 lease 和 fencing token，
  通过 BlobStore/ParserRegistry 解析，并在一个完成事务中写入 immutable chunks、attempt history 和 audit；
- 解析失败按稳定错误码落为 failed，成功结果更新版本统计；过期 lease 可安全将 processing job 重排队，
  下一次领取会递增 attempt/fencing token；
- 独立 worker 进程入口、心跳循环、Redis 唤醒和 Compose readiness 已接入并通过集成验证。

## 3. 最近验证结果

截至当前切片已执行：

- API 非集成：`260 passed, 2 skipped, 6 deselected`；
- 上传 API、读取接口与应用生命周期：`14 passed`；
- 新增配置边界、生命周期、chunked body、提交失败清理和审计脱敏回归测试；
- Web：`66 passed`；
- 根目录 `make lint`、`make typecheck`、`make test`、`make build` 全部通过；
- `uv lock --directory apps/api --check` 和 Shell 语法检查通过；
- Web lint、typecheck、build：通过；
- API Ruff check/format、mypy、`uv lock --check`、Shell 语法：通过；
- macOS 没有 bubblewrap，所以真实 bwrap 测试按条件跳过；Linux CI 会执行；
- 真实 PostgreSQL/Redis/Worker 集成测试：`6 passed, 251 deselected`，包含迁移头、真实 LocalBlobStore
  并发版本上传、Worker 并发解析闭环和 readiness；
- 开发认证切片：`DEV_ACTOR_ID` 仅在 development 生效，种子脚本幂等创建本地组织、项目和管理员
  membership；认证边界测试通过，运行态 `/api/projects` 返回 200，未配置认证时仍保持 501 fail-closed；
- JWT 认证切片：可通过 `AUTH_MODE=jwt_hs256` 启用依赖无关的 HS256 Bearer token 校验，强制验证
  签名、issuer、audience、exp、nbf 和 UUID 身份声明，并用数据库 membership 确认 token 组织；完整
  OIDC/JWKS、非对称密钥轮换、登录/刷新会话、撤销策略和认证审计仍是后续发布缺口；

当前文档摄取基础、候选生成、实验、指标、Trace/失败回归和设置页已完成对应 MVP 切片；本分支
仍未合并回 `main`，但最新提交已推送远程。

## 4. 尚未完成且必须先处理的阻断项

文档摄取 HTTP/存储/执行基础闭环已完成。保留的产品与发布质量缺口如下：

1. **认证**：本地 development actor 已接入并通过 membership 推导租户；当前仅有受控部署可用的 HS256
   boundary，真实 OIDC/JWKS provider、非对称密钥轮换、登录/刷新会话和撤销策略尚未接入，development
   actor 不能替代生产认证。
2. **产品契约**：成本费率、检索证据指标和完整全链路 E2E/Playwright 仍需补齐。

本轮已解决 Docker Hub pinned Python 镜像返回 `403 Forbidden` 的构建阻断：API/Web/Worker 改用
内容 digest 相同的 Amazon ECR Public 官方镜像源；若网络无法访问 `public.ecr.aws`，应配置等价
镜像代理并保持相同 digest。

## 5. 下一阶段路线

后续按实施计划继续：

1. 将 Blob 对账接入 worker 维护入口，补齐 worker 进程、心跳/批量循环和 Compose readiness。
2. 实现持久化 `JobRepository`：PostgreSQL `FOR UPDATE SKIP LOCKED`、lease/heartbeat、
   fencing token、append-only attempt、取消/重试/崩溃恢复；所有副作用写入必须验证 token。
3. 实现可独立运行的 `python -m rag_eval_api.worker`，使用 `ParserRunner` 读取 BlobStore，
   成功后写 immutable chunks；失败必须保留 error code、attempt 和 audit。
4. 增加 Compose worker 服务、readiness/health、worker 集成测试和 CI PostgreSQL 任务。
5. 将 `apps/web/src/app/(app)/documents/page.tsx` 从 placeholder 替换为管理页面：摘要卡、
   搜索/筛选、语义化表格、上传 dialog、进度/取消、retry/archive/action 权限和 job polling。
6. 更新 OpenAPI 生成类型和 Web API client；为 Documents 页面补 loading、empty、error、
   no-result、permission、reduced-motion、键盘焦点和 Playwright 测试。
7. 候选生成必须保持 opt-in：没有 provider 时只能 `blocked/provider_not_configured`，
   绝不能伪造评测数据；再实现版本化 CandidateGenerator 和 provider URL 安全边界。

## 6. 重要文件入口

- API 入口：[main.py](../apps/api/src/rag_eval_api/main.py)
- 上传路由：[documents.py](../apps/api/src/rag_eval_api/routes/documents.py)
- 上传 schema：[ingestion.py](../apps/api/src/rag_eval_api/schemas/ingestion.py)
- BlobStore：[local.py](../apps/api/src/rag_eval_api/storage/local.py)
- parser 沙箱：[runner.py](../apps/api/src/rag_eval_api/parsers/runner.py)
- ingestion 状态原语：[ingestion_jobs.py](../apps/api/src/rag_eval_api/services/ingestion_jobs.py)
- API 测试：[test_documents_api.py](../apps/api/tests/test_documents_api.py)
- CI：[ci.yml](../.github/workflows/ci.yml)

## 7. 建议的接续命令

```bash
cd /Users/yanxs/code/ai_coding/rag-eval-platform/.worktrees/mvp-foundation-admin-shell
git status --short
git log -5 --oneline
uv run --directory apps/api pytest -m 'not integration' -q
make lint typecheck test build
```

本轮最新验证：根目录 `make lint`、`make typecheck`、`make test`、`make build`、`make test-integration`
全部通过；API `249 passed, 2 skipped, 6 deselected`，Web `66 passed`。官方 npm audit（使用
`https://registry.npmjs.org`）和 Python `pip-audit --skip-editable --strict --local` 均无已知漏洞。
`make test-integration` 已在隔离 Compose 中完成 PostgreSQL/Redis/Worker 启动、Alembic `0015` 空库
迁移、`alembic check` 和 API integration；Playwright 尚未在本机执行。此前修复的迁移回归包括
`0005` check constraint 字面命名、`0012/0013/0014` asyncpg 多语句执行问题，以及 `0015` 对齐
历史索引/租户外键与 ORM 元数据。

继续修复代码时遵循 TDD：先新增能准确表达问题的失败测试，确认红灯，再写最小实现，最后跑相关
测试、全量门禁和独立评审。不要把 `.docker/`、`.env`、构建产物或测试数据提交到仓库。
