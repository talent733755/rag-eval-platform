# 项目接手文件

> 更新时间：2026-09-11
> 当前工作目录：`/Users/yanxs/code/ai_coding/rag-eval-platform/.worktrees/mvp-foundation-admin-shell`
> 当前分支：`codex/mvp-foundation-admin-shell`
> 当前提交：`d1db722 feat: add document upload api`

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

## 3. 最近验证结果

在 `d1db722` 及其父提交上已执行：

- API 非集成：`168 passed, 2 skipped, 4 deselected`；
- 上传 API：`7 passed`；
- Web：`54 passed`；
- Web lint、typecheck、build：通过；
- API Ruff check/format、mypy、`uv lock --check`、Shell 语法：通过；
- macOS 没有 bubblewrap，所以真实 bwrap 测试按条件跳过；Linux CI 会执行；
- 真实 PostgreSQL 集成测试此前已通过：`4 passed, 159 deselected`。

当前工作树在整理本文件前是干净的；本文件新增后需要单独提交。

## 4. 尚未完成且必须先处理的阻断项

上传 API 当前不能视为完成。最近独立契约/安全评审均为 `Not Spec compliant` / `Not
Approved`，主要问题如下：

1. **生产应用没有装配 BlobStore。** `routes/documents.py` 只读取
   `app.state.blob_store`，`create_app()` 尚未从 `Settings.blob_root` 创建并关闭
   `LocalBlobStore`，真实应用会默认返回 `503 blob_storage_not_configured`。
2. **请求级 multipart body 没有在解析前硬限制。** 路由内的 `_inspect_upload()` 只能限制
   已经被 Starlette multipart parser 接收后的文件；必须在 ASGI receive/middleware 层限制
   整个请求体，避免超大 chunked 请求或额外 multipart 字段耗尽临时磁盘/内存。仍需保留
   路由和 BlobStore 两层限制。
3. **Blob 发布和数据库提交不是同一事务。** BlobStore 发布成功后若数据库提交失败、
   进程崩溃或发布阶段异常，可能留下无引用对象。至少要：发布后任何已知失败路径删除
   opaque key；补普通 `Exception` 清理；并为进程崩溃场景设计 orphan reconciliation/GC，
   不能声称单靠 HTTP 事务解决。
4. **空文件状态码语义。** 当前返回 `413 size_exceeded`，契约评审建议改为 `422
   validation_error`；需同步测试和公共契约。
5. **审计敏感性。** 当前 metadata 原样保存用户提供的 `Idempotency-Key`，应改为保存
   截断后的安全标识或 key hash，不把可控 header 原样写入审计记录。
6. **测试缺口。** 需增加真实 `LocalBlobStore`、数据库提交失败、发布后清理、请求体硬上限、
   跨组织、并发唯一冲突和生产 app 默认 BlobStore 装配测试。SQLite 不能替代 PostgreSQL
   约束/并发集成测试。

处理顺序建议：先补测试使上述问题红灯，再修 `main.py`/BlobStore 生命周期和 ASGI body
limit；然后修上传事务清理与审计字段；最后跑全量质量门禁和双人评审。

## 5. 下一阶段路线

修复上述上传 API 阻断项后，按实施计划继续：

1. 增加显式 document version upload、Documents 查询/详情/versions、retry parse、job
   polling/cancel API；统一 cursor、状态、错误 envelope 和权限。
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
