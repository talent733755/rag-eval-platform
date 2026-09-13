# Experiment v1

实验配置在创建运行记录前必须通过同一组项目作用域校验：

- `dataset_version_id` 必须属于当前项目，且状态为 `published`；
- `adapter_config_id` 必须属于当前项目、已启用，并且最近一次连接测试成功；
- `model_provider_id` 必须属于当前项目且已启用；
- `random_seed` 必须由调用方明确提供；
- `parameters` 最多 100 个顶层字段，序列化后不超过 64 KiB；
- `metric_versions` 是创建时固定的指标版本引用。

服务在启动实验时生成不可变快照，快照至少包含评测集版本、Adapter 配置 ID 与版本、模型
Provider ID 与模型名、指标版本、参数、随机种子和运行环境 hash。Provider 的密钥只从部署
配置注入，不写入快照、审计、Trace 或日志。任何依赖不可用都返回稳定错误码（例如
`dataset_version_unpublished`、`adapter_unavailable`、`provider_unavailable`），不会创建
可运行的假任务。
