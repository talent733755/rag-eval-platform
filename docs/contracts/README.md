# 公共契约索引

- [`document-ingestion-v1.md`](document-ingestion-v1.md)：文档上传、版本、解析任务和 Worker 状态。
- [`candidate-generation-v1.md`](candidate-generation-v1.md)：候选生成请求、证据和 Provider 错误。
- [`adapter-v1.md`](adapter-v1.md)：RAG Adapter 请求、响应、引用、用量和 Trace。

OpenAPI 类型通过仓库根目录的 `pnpm generate:web-api` 生成到 `apps/web/src/lib/api/generated.ts`。契约版本只能兼容新增；改变字段含义、状态迁移或安全边界时必须增加版本并写迁移说明。
