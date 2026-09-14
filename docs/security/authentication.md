# 认证边界

当前 API 的认证依赖 `get_current_actor`，默认 fail-closed：生产、staging 或未配置开发 actor
时返回 `501 not_implemented`，不会信任请求头、URL、JSON body 或客户端传入的 user/org ID。
本地 `APP_ENV=development` 可以显式配置 `DEV_ACTOR_ID`，API 仅从数据库 membership 推导其唯一
organization；`scripts/seed-dev-data.py` 提供幂等的本地组织、项目和管理员 membership。测试仍通过
FastAPI dependency override 注入 `RequestActor`，生产配置不允许使用 development 默认密钥。

当前提供的可替换 JWT boundary 使用明确配置的 HS256：设置 `AUTH_MODE=jwt_hs256`、至少 32 个字符的
`AUTH_JWT_SECRET`、精确的 `AUTH_JWT_ISSUER` 和 `AUTH_JWT_AUDIENCE`。Token 必须包含 `sub`、
`organization_id`、`iss`、`aud` 和 `exp`；组织声明还必须通过数据库 membership 校验。HS256 适合受控
的内部部署；公网多服务部署仍应接入 OIDC/JWKS provider，并替换为非对称签名和密钥轮换方案。

正式部署必须接入可替换的 OIDC/JWT provider，在边界完成签名、issuer、audience、过期时间和
撤销策略校验，再向下游只传递 `user_id` 与 `organization_id`。项目角色继续由数据库 membership
查询决定；任何资源查询都必须同时限制组织和项目，不能把 JWT claim 当作项目授权。

禁止把 access token、refresh token、Authorization header 或 provider 原始响应写入日志、审计
metadata、Trace、快照或错误响应。认证接入完成前不得将当前 `501` 行为改成“默认用户”或“默认
组织”。
