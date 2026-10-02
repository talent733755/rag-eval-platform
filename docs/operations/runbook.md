# 运行手册（MVP）

## 启动与检查

```bash
make infra-up
uv run --directory apps/api alembic upgrade head
uv run --project apps/api python scripts/seed-dev-data.py
uv run --directory apps/api uvicorn rag_eval_api.main:app --host 127.0.0.1 --port 8003
uv run --directory apps/api python -m rag_eval_api.worker
NEXT_PUBLIC_API_BASE_URL=http://localhost:8003 corepack pnpm --dir apps/web dev -- --port 3003
```

检查 `/health/live` 判断进程存活，检查 `/health/ready` 判断 PostgreSQL、Redis 和 Worker
readiness。Worker 使用 PostgreSQL 任务状态作为事实来源，Redis 不可用时只影响唤醒提示。

本地开发必须在 `.env` 中保留 `APP_ENV=development` 和 `DEV_ACTOR_ID`，并在首次启动或重置数据库后
执行迁移和 `scripts/seed-dev-data.py`。访问 Web 后若看到 `HTTP 501`，先检查是否误以为
`Authorization` 请求头可以替代认证；未启用 JWT 时生产认证仍未配置，开发 actor 也不会读取任何请求头。

## 数据与敏感信息

Provider、Adapter 的密钥只配置为进程环境变量引用；数据库只保存 `credential_ref`。Trace
payload 先脱敏，64 KiB 以内才内联，较大内容使用私有 BlobStore opaque key。不要把真实用户
文档、问题、答案、token 或上游错误复制到 Issue/日志。

## 故障处理

查看实验 Run、失败案例和 Trace 页面，依据稳定 `error code` 排障。失败项可单独重试；指标
可通过幂等重算接口补写派生结果。不要直接修改或删除 experiment、metric、Trace、failure
和 regression history；这些表由应用和 PostgreSQL append-only 边界共同保护。

## 私有部署与生产认证

生产环境必须关闭开发 actor（`DEV_ACTOR_ID` 仅在 `APP_ENV=development` 下允许），并启用一种真实认证边界：

- **HS256 JWT（`AUTH_MODE=jwt_hs256`）**：设置 `AUTH_JWT_SECRET`（≥32 字符）、`AUTH_JWT_ISSUER`、`AUTH_JWT_AUDIENCE`。适用于平台自行签发令牌。
- **OIDC / RS256（`AUTH_MODE=oidc`）**：设置 `AUTH_OIDC_JWKS_URL`（必须 https）、`AUTH_OIDC_ISSUER`、`AUTH_OIDC_AUDIENCE`；平台从该 URL 拉取 JWKS 公钥并缓存 `AUTH_OIDC_JWKS_CACHE_SECONDS`，未知 key id 触发单次刷新以支持非对称密钥轮换。适用于接入企业 IdP（如 Entra ID、Keycloak、Auth0）。

认证失败（无效令牌、无组织权限）会以 `auth.failed` 审计事件 best-effort 记录到组织边界，永不阻塞请求。生产镜像使用 pinned digest 的 Amazon ECR Public 官方镜像源；如所在网络无法访问 `public.ecr.aws`，需为 Docker 配置可访问的等价镜像代理，并保持相同内容 digest。

当前已知限制：登录/刷新会话与撤销策略（refresh token、session revocation）尚未接入，Bearer 令牌无服务端会话状态；成本指标尚无费率契约。
