# 项目接手文件

> 更新时间：2026-09-12
> 当前工作目录：`/Users/yanxs/code/ai_coding/rag-eval-platform/.worktrees/mvp-foundation-admin-shell`
> 当前分支：`codex/mvp-foundation-admin-shell`
> 当前提交：当前分支最新提交（持久化解析 Worker 核心）

## 1. 接续规则

下次继续工作时，先阅读本文件、根目录 `AGENTS.md`、
`docs/superpowers/plans/2026-09-10-document-ingestion-and-candidate-data.md`，再检查
`git status` 和当前提交。不要从项目历史重新推导需求，也不要把当前阶段代码当成
Demo 交付。本项目的铁律是按完整 GitHub 开源项目建设：公共契约、异常处理、测试、
安全、可观测性、许可证、CI 和文档都必须同步演进。

当前分支是独立 worktree，尚未合并回 `main`，也没有要求再次 push 远程仓库。

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
- 当前仍缺独立 worker 进程入口、心跳循环、Redis 唤醒和 Compose readiness。

## 3. 最近验证结果

截至当前切片已执行：

- API 非集成：`182 passed, 2 skipped, 5 deselected`；
- 上传 API、读取接口与应用生命周期：`14 passed`；
- 新增配置边界、生命周期、chunked body、提交失败清理和审计脱敏回归测试；
- Web：`54 passed`；
- 根目录 `make lint`、`make typecheck`、`make test`、`make build` 全部通过；
- `uv lock --directory apps/api --check` 和 Shell 语法检查通过；
- Web lint、typecheck、build：通过；
- API Ruff check/format、mypy、`uv lock --check`、Shell 语法：通过；
- macOS 没有 bubblewrap，所以真实 bwrap 测试按条件跳过；Linux CI 会执行；
- 真实 PostgreSQL 集成测试：`5 passed, 181 deselected`，包含真实 LocalBlobStore 的并发版本上传闭环；

当前切片工作树干净；本分支仍未合并回 `main`，也未推送远程。

## 4. 尚未完成且必须先处理的阻断项

上传 API、读取/任务 API、显式版本上传、孤儿 Blob 对账基础与解析 worker 核心已经形成文档摄取
HTTP/存储/执行基础闭环，但仍不能视为完整文档摄取垂直闭环；后续还需补充 worker 进程入口和
Documents UI。
保留的质量缺口如下：

1. **运行时入口** 尚未提供独立 worker 进程、心跳循环、Redis 唤醒和 Compose readiness；HTTP 事务
   清理仍不能单独覆盖进程崩溃。
2. **测试缺口**：跨组织、并发唯一冲突与 worker 端到端 PostgreSQL 覆盖仍需扩充；SQLite
   不能替代 PostgreSQL 约束/并发集成测试。

下一步建议：补齐 worker 进程入口、心跳/批量循环和 Compose 集成，再进入 Documents UI。

## 5. 下一阶段路线

修复上述上传 API 阻断项后，按实施计划继续：

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

修复上传 API 时遵循 TDD：先新增一个能准确表达阻断问题的失败测试，确认红灯，再写最小
实现，最后跑相关测试、全量门禁和独立双人评审。不要 push 或合并，除非用户明确要求。
