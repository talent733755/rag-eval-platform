# 认证边界

当前 API 的认证依赖 `get_current_actor`，默认 fail-closed：未接入真实身份提供方时返回
`501 not_implemented`，不会信任请求头、URL、JSON body 或客户端传入的 user/org ID。测试和
本地确定性 fixture 只能通过 FastAPI dependency override 注入 `RequestActor`，且生产配置不
允许使用 development 默认密钥。

正式部署必须接入可替换的 OIDC/JWT provider，在边界完成签名、issuer、audience、过期时间和
撤销策略校验，再向下游只传递 `user_id` 与 `organization_id`。项目角色继续由数据库 membership
查询决定；任何资源查询都必须同时限制组织和项目，不能把 JWT claim 当作项目授权。

禁止把 access token、refresh token、Authorization header 或 provider 原始响应写入日志、审计
metadata、Trace、快照或错误响应。认证接入完成前不得将当前 `501` 行为改成“默认用户”或“默认
组织”。
