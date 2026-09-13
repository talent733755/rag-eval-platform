# 变更记录

## 未发布

- 增加成员管理与模型服务设置页面，接入项目作用域 API 和权限边界。
- 增加真实指标 Dashboard、Trace/失败诊断、回归集基础和脱敏持久化查询。
- 增加实验运行控制台、取消/失败项重试和可恢复 Run 记录。
- 增加独立持久化解析 Worker、租约/fencing、readiness 检查和 Compose 运行时。
- 增加版本化候选生成契约、安全的 OpenAI-compatible Provider 边界，以及未配置 Provider 时的诚实错误。
- 增加文档批量上传、归档引用保护、Documents 页面和候选评测集版本审核/发布 API。
- 增加 `adapter-v1`、metrics、Trace 公共协议层和开源协作、安全、发布文档。

正式发布前仍需完成真实 OIDC/JWT 认证、有限重试/取消中断、Provider 费率与成本指标、检索证据
评测、完整文档到回归集 E2E、Compose 集成验证和依赖审计闭环。
