# 发布检查清单

本文描述 RAG Eval Platform 发布前的可复现检查。项目当前为 `0.1.0` 开发阶段；在创建正式
版本前，必须先确认本文中的限制项已处理，或在发布说明中明确标为不支持。

## 1. 工作区与版本

```bash
git status --short
git diff --check
git log -1 --oneline
```

确认没有 `.env`、密钥、用户数据、临时目录、`apps/web/.next`、Playwright 结果目录或其他
构建产物。版本号需要同步检查根目录 `package.json`、`apps/web/package.json` 和
`apps/api/pyproject.toml`，公共契约破坏性变更需要增加迁移说明。

## 2. 质量门禁

在仓库根目录执行：

```bash
make lint
make typecheck
make test
make build
```

涉及数据库或 Worker 时还必须执行：

```bash
make test-integration
```

该命令使用隔离的 Compose 项目和临时测试数据库，基础镜像来自 pinned digest 的 Amazon
ECR Public 官方镜像源。失败时应保留错误码与服务状态，但不得上传密钥、完整文档或
原始 Provider 响应。

## 3. 契约与浏览器检查

修改 API 路由或 schema 后执行 OpenAPI 生成检查：

```bash
corepack pnpm generate:web-api
git diff --exit-code -- apps/web/src/lib/api/generated.ts
```

涉及管理后台交互时执行：

```bash
corepack pnpm --dir apps/web e2e
```

Playwright 必须使用仓库内确定性拦截或 fixture，不得调用真实模型、Embedding、Reranker、
向量数据库或真实用户账号。

## 4. 依赖、许可证和安全

直接解析依赖的许可证记录在
[`docs/legal/dependency-licenses.md`](../legal/dependency-licenses.md)。升级依赖时需要：

```bash
uv lock --directory apps/api --check
corepack pnpm install --frozen-lockfile
npm_config_registry=https://registry.npmjs.org corepack pnpm audit --prod --audit-level=high
uv run --directory apps/api --with pip-audit pip-audit --skip-editable --strict --local
```

审计命令需要访问包索引或漏洞数据库，网络不可用时不能把失败解释为“无漏洞”；应记录为
发布阻塞或已知限制。高危/严重漏洞不得带入正式发布。新增直接依赖必须更新许可证清单，
并确认维护状态、许可证兼容性和运行时用途。

## 5. 数据与认证边界

- `SECRET_KEY` 必须使用部署环境注入的随机值，不能使用 `.env.example` 占位值。
- Provider/Adapter 凭据只能通过安全的进程环境引用进入运行时，不能写入数据库、日志、Trace
  或浏览器存储。
- 发布前必须确认租户复合授权、append-only 历史表和审计事件测试通过。
- 当前版本提供受控部署用的 `AUTH_MODE=jwt_hs256` HS256 边界，但尚未接入真实 OIDC/JWKS provider、
  非对称密钥轮换、登录/刷新会话和撤销策略；因此只能作为受控开发/MVP 发布，不能宣称具备完整生产
  认证能力。

## 6. 发布记录

发布说明至少包含：版本、变更摘要、数据库迁移、兼容性/迁移方式、验证命令与结果、安全和
隐私影响、依赖审计日期，以及未完成项。推荐先在独立分支完成检查，再创建受保护的版本标签。
