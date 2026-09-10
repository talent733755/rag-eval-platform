# RAG Eval Platform

开源的 RAG 评测数据工程与检索链路实验平台。

## 本地开发

### 前置条件

请先安装以下工具：

- Node.js `>=20.0.0 <25.0.0` 与 Corepack 管理的 pnpm
- Python `>=3.12,<3.13`（Python 3.12.x）与 uv
- GNU Make
- Docker Engine 或 Docker Desktop，以及 Docker Compose

### 当前仓库状态

当前仓库已经包含可运行的项目基础设施和管理后台骨架：

- `apps/api`：FastAPI API、健康检查、项目与成员基础接口、SQLAlchemy/Alembic 数据层和结构化错误响应；
- `apps/api/src/rag_eval_api/storage`：私有、原子、不可覆盖的 LocalBlobStore；
- `apps/api/src/rag_eval_api/parsers`：PDF、DOCX、Markdown、UTF-8 文本的有界解析器与 canonical chunk 契约；
- `apps/web`：Next.js 管理后台壳层、权限感知菜单、项目切换器和占位业务页面；
- `apps/web/src/lib/api/generated.ts`：由 FastAPI OpenAPI 文档生成的 TypeScript 类型；
- `docker-compose.yml`：PostgreSQL、Redis、API 和 Web 的本地容器编排；
- `.github/workflows/ci.yml`：API/Web 质量门禁、本地集成检查、OpenAPI client diff 校验和 Playwright smoke；
- `apps/web/e2e/admin-shell.spec.ts`：不依赖外部服务的管理后台浏览器冒烟测试。

当前版本仍然是基础平台闭环，文档导入与评测集工厂、Pipeline Adapter 执行、实验任务、指标计算、Trace/失败诊断、真实认证和异步任务编排尚未实现；这些边界会在后续迭代中按公共契约逐步加入。

当前文档摄取阶段已经完成 BlobStore 与解析器基础设施，但还没有开放 HTTP 上传路由或
worker 进程。直接调用它们的最小本地示例（不会联网，也不会调用模型）如下：

```python
from io import BytesIO

from rag_eval_api.parsers.registry import ParserRegistry
from rag_eval_api.storage.local import LocalBlobStore

blob = LocalBlobStore("/var/lib/rag-eval/blobs")
stored = blob.put(BytesIO(b"# Hello\n\nA deterministic chunk."))
with blob.open(stored.storage_key) as source:
    parsed = ParserRegistry().parse(
        source,
        filename="guide.md",
        declared_mime="text/markdown",
    )
print(stored.sha256, parsed.parser_version, parsed.chunks[0].source_location)
```

生产部署仍需将 BlobStore 根目录放在非公开的持久化卷，并在非特权、资源受限的
容器或等价 sandbox 中处理不可信文档；进程内 parser limits 不能替代操作系统隔离。

### 初始化

在仓库根目录执行。`make install` 使用已提交的 `pnpm-lock.yaml` 和 `apps/api/uv.lock`，确保依赖可复现：

```bash
make install
cp .env.example .env
make infra-up
```

`make infra-up` 只启动 PostgreSQL 和 Redis。API 和 Web 开发服务分别在两个终端启动。

终端 1：启动 API（仅绑定本机回环地址）：

```bash
uv run --directory apps/api uvicorn rag_eval_api.main:app --reload --host 127.0.0.1 --port 8000
```

终端 2：启动 Web：

```bash
corepack pnpm --dir apps/web dev
```

API 的本机开发命令默认不会暴露到局域网。Compose、反向代理或公网部署应使用各自的
网络、端口映射和 TLS/访问控制配置，不要把本机开发命令直接当作公网启动方案。

也可以在完成 `.env` 配置后使用 `docker compose up -d` 启动 Compose 中定义的全部服务。

Web 壳层通过 `GET /api/projects` 加载当前 actor 可见的项目。可用
`NEXT_PUBLIC_API_BASE_URL` 指向 API 地址；未设置时默认为
`http://localhost:8000`。项目选择保存在 URL 的 `project` 查询参数中，API
加载失败或 URL 中的项目不可见时不会自动切换到其他项目。

启动 API 和 Web 后，API 地址为 <http://localhost:8000>，Web 地址为 <http://localhost:3000>。API 的 OpenAPI 文档地址为 <http://localhost:8000/openapi.json>。

当 API 运行在 Compose 容器中时，Compose 配置必须将 `COMPOSE_DATABASE_URL` 和 `COMPOSE_REDIS_URL` 注入容器内的 `DATABASE_URL` 和 `REDIS_URL`。这两个 Compose 连接串使用内部服务 DNS 名称 `postgres` 和 `redis`，容器间连接不能使用 `localhost`。

### 质量检查

提交变更前执行以下四个质量命令。它们是本项目要求的质量门禁：

```bash
make lint
make typecheck
make test
make build
```

### API 客户端与浏览器冒烟

Web API 类型由 FastAPI 的真实 OpenAPI 文档生成，生成工具和版本锁定在
`apps/web/package.json` 与 `pnpm-lock.yaml` 中。不要直接编辑生成文件；修改 API
路由或 schema 后运行：

```bash
pnpm generate:web-api
git diff --exit-code -- apps/web/src/lib/api/generated.ts
```

本地浏览器冒烟测试使用 Playwright，并在测试内拦截 `/api/projects` 为确定性项目数据，
因此不依赖外部服务或真实用户凭据。首次运行需安装 Chromium：

```bash
pnpm install --frozen-lockfile
pnpm --dir apps/web exec playwright install chromium
pnpm --dir apps/web e2e
```

已知本机限制：某些 macOS 环境启动 Playwright Chromium 可能返回系统错误 `-88`。
这表示本机浏览器运行时不兼容，不代表 Web 代码或冒烟断言失败；遇到此问题时，建议
使用 GitHub Actions 的 Ubuntu runner，或在 Linux/Docker 环境运行。失败时的 trace、
截图和视频等诊断产物位于本地 `apps/web/test-results/`；GitHub Actions 会将该目录
作为 `playwright-traces` artifact 上传。

GitHub Actions 会在 Pull Request 和 `main` 分支 push 上运行 API/Web 质量门禁、本地
PostgreSQL/Redis 集成检查、生成客户端 diff 校验和 Playwright 冒烟；浏览器失败时仅
上传测试结果目录中的 trace 等诊断产物，不上传 secrets。

使用 `make infra-down`（即 `docker compose down`）停止整个 Compose 项目，而不只是 PostgreSQL 和 Redis。非开发环境启动 API 前，必须将 `SECRET_KEY` 的本地占位符替换为生成的密钥。`.env`、本地生成的密钥和其他生成的敏感信息永远不会提交到版本库；请勿将真实凭据写入 `.env.example`。

## 产品定位

面向 RAG/AI 工程师，从企业原始文档自动构建可追溯、可审核、可持续迭代的评测集，并用于评估、对比和诊断完整的 RAG Pipeline。

一句话概括：

> 不要求用户事先拥有黄金评测集，而是从原始知识库开始，构建评测数据，再定位切分、查询改写、召回、重排和生成阶段的问题。

## 要解决的问题

企业通常只有 PDF、Word、Markdown、网页或内部文档，却缺少：

- 有代表性的评测问题
- 可验证的标准答案
- 与答案绑定的标准证据
- 能够区分检索问题和生成问题的诊断数据
- 可以用于版本回归的稳定评测集

与此同时，RAG 的最终质量会受到整条链路影响：

```text
文档解析 → 文档切分 → 索引 → 查询改写 → 多路召回 → 合并 → 重排 → 上下文组装 → 答案生成
```

只看最终答案分数，通常无法回答“为什么答错”和“应该改哪一环”。

## 核心价值

平台需要形成以下闭环：

```text
原始文档
  ↓
评测问题、标准答案、标准证据候选
  ↓
自动校验与人工审核
  ↓
可版本化评测集
  ↓
多组 RAG Pipeline 实验
  ↓
阶段指标、检索 Trace 与失败诊断
```

核心目标不是只给出一个“回答得分”，而是解释：

```text
回答失败
→ 标准证据没有进入 Top-K
→ 查询改写丢失了关键实体
→ 向量检索没有召回
→ 关键词检索能够召回但权重过低
→ 重排阶段又将正确证据排除
```

## 目标用户

主要用户是：

- RAG 工程师
- AI 应用工程师
- LLM 平台工程师
- 负责知识库问答质量的算法工程师

他们关心的是：

- 哪种切分策略效果更好
- 父子块是否真正提升了召回
- 查询改写是否改变了用户意图
- 混合检索带来了多少增益
- 重排是否改善了候选排序
- Embedding、Reranker 或 LLM 更换后是否发生回归
- 如何将评测接入 CI/CD

## 核心模块

### 1. 评测集工厂

从原始文档生成评测数据候选，并保留完整来源关系：

```text
文档导入
→ 内容解析
→ 证据片段提取
→ 问题生成
→ 答案生成与证据绑定
→ 自动质量检查
→ 人工审核
→ 数据集版本管理
```

每条评测数据至少应能追溯到：

- 原始文档
- 文档版本
- 页码或段落位置
- 标准证据片段
- 参考答案
- 问题类型
- 自动检查结果
- 人工审核状态

### 2. RAG Pipeline 实验平台

支持对比不同的 RAG 配置：

- 文档解析与切分策略
- Parent-Child Chunking
- 向量检索
- 关键词检索
- 混合检索
- 查询重写
- HyDE 等查询扩展策略
- Reranker
- 上下文组装
- 最终回答模型

平台不负责替代向量数据库、Embedding 服务或现有 RAG 框架，而是通过 Adapter 接入已有系统。

### 3. 阶段评测与诊断

检索层：

- Recall@K
- Precision@K
- Hit Rate
- MRR
- nDCG
- 证据命中率
- 父块覆盖率
- 多路检索互补率

生成层：

- Answer Correctness
- Faithfulness
- Citation Correctness
- Context Precision
- Context Recall
- 拒答准确率

工程指标：

- 延迟
- Token 消耗
- API 成本
- 失败率

### 4. Trace 与实验对比

单条问题应能查看完整过程：

```text
原始问题
→ 查询改写结果
→ 各路检索候选
→ 合并结果
→ 重排结果
→ 最终上下文
→ 模型回答
→ 标准答案与标准证据
→ 失败原因
```

实验层面支持比较：

- 不同切分策略
- 不同 Query Rewrite 策略
- 不同 Top-K 和检索权重
- 不同父子块配置
- 不同 Reranker
- 不同模型组合

### 5. 回归与质量门

将评测结果接入 CI/CD：

```text
Pipeline 或知识库变更
  ↓
运行回归数据集
  ↓
与基线比较
  ↓
指标下降超过阈值
  ↓
阻止发布并输出失败样例
```

## 评测数据状态

自动生成的数据不能直接被视为黄金标准，建议区分：

```text
自动生成候选集
  ↓
自动质量检查
  ↓
人工审核
  ↓
Gold Dataset
```

平台需要明确标识每条数据的状态、来源和置信度，避免把模型生成的答案当作未经验证的真值。

## 问题类型

评测集应覆盖不同难度和风险：

- 直接事实查询
- 同义改写问题
- 多跳问题
- 跨文档问题
- 表格和结构化数据问题
- 时间和版本敏感问题
- 无法回答问题
- 容易混淆的问题
- 需要拒答的问题

## 产品边界

本项目不以这些方向为首要目标：

- 不自研向量数据库
- 不替代 LangChain、LlamaIndex 或 Dify
- 不负责企业知识库生产管理
- 不绑定某一个 Embedding、Reranker 或 LLM 厂商
- 不把最终答案分数作为唯一评测结果

本项目专注于：

- 评测数据工程
- RAG Pipeline Adapter
- 可复现实验执行
- 分阶段指标计算
- 检索 Trace
- 失败诊断
- 多配置对比
- CI 回归

## 首个产品闭环

第一版的目标体验：

```text
上传原始文档
→ 自动生成 20 条候选评测问题
→ 查看问题、参考答案和证据
→ 人工审核
→ 接入一个 RAG Pipeline
→ 运行首次评测
→ 查看总体指标和失败 Trace
```

## 与旧项目的关系

同级的 `agent_eval` 是早期的 DSPy + Promptfoo 营销 Agent 评测 PoC，主要关注 Prompt 优化和 Agent 输出质量。

本项目从原始文档和 RAG Pipeline 出发，关注知识库评测数据构建、检索链路实验和问题诊断。两者暂不共享代码，避免旧的营销 Agent 领域模型和新的知识库评测模型混在一起。

## 开源项目工程原则

本项目以构建完整、可长期维护、可被社区使用和贡献的 GitHub 开源项目为目标，而不是一次性 Demo。后续所有代码、架构和工程决策必须遵守根目录 `AGENTS.md` 中的开源工程规则。

最低要求包括：

- 公共接口、配置、数据格式和 Adapter 协议必须有明确文档，并考虑兼容性和版本演进。
- 新功能必须配套测试、错误处理、日志/可观测性和必要的使用示例。
- 代码不得依赖本地私有环境、硬编码密钥或未说明的厂商服务；依赖和许可证必须可审计。
- 变更必须经过格式化、静态检查、类型检查（如适用）、测试、构建和安全检查等质量门禁。
- 架构优先考虑模块化、可扩展、可替换和可复现，不能为了演示效果留下不可维护的临时实现。
- 面向社区使用的文档、贡献流程、行为准则、安全漏洞报告、变更记录和发布版本会作为项目逐步完善的正式组成部分。
