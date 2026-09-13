# 公共契约索引

- [`document-ingestion-v1.md`](document-ingestion-v1.md)：文档上传、版本、解析任务和 Worker 状态。
- [`candidate-generation-v1.md`](candidate-generation-v1.md)：候选生成请求、证据和 Provider 错误。
- [`adapter-v1.md`](adapter-v1.md)：RAG Adapter 请求、响应、引用、用量和 Trace。
- [`metrics-v1.md`](metrics-v1.md)：指标纯函数、缺失语义、版本和结果持久化契约。
- [`experiment-v1.md`](experiment-v1.md)：实验草稿启动校验和不可变快照边界。
- [`trace-v1.md`](trace-v1.md)：脱敏 Trace 阶段、Blob 引用、失败分类和查询边界。

Adapter 配置 API 使用项目权限：成员可读，编辑者可改，管理员可删。Python Adapter 的
`entrypoint_ref` 只能解析部署中已安装且唯一的 `rag_eval_adapter` entry point。连接测试会产生一次
受控的 `/invoke` 请求，部署时必须配置 `PROVIDER_ALLOWED_HOSTS` 和
`PROVIDER_ALLOWED_PORTS`，否则网络目的地不会被允许。

OpenAPI 类型通过仓库根目录的 `pnpm generate:web-api` 生成到 `apps/web/src/lib/api/generated.ts`。契约版本只能兼容新增；改变字段含义、状态迁移或安全边界时必须增加版本并写迁移说明。
