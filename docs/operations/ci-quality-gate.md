# CI 质量门集成

`rag-eval-platform` 把"这次 RAG 改动是否回退"变成一个**确定性、可审计**的服务端判定，
再通过一个薄封装 GitHub Action 接入流水线。判定逻辑全部在服务端（见
[`docs/contracts/quality-gate-v1.md`](../../contracts/quality-gate-v1.md)），Action 只负责
轮询运行状态、提交阈值、按结果退出，因此同一套门禁可被本地脚本、CI 与任意客户端复用。

## 前置条件

1. 平台已部署并可被 CI 访问（`API_BASE_URL`）。
2. 一个具备项目 **member** 权限的令牌（只读门禁即可，无需写权限）。
3. 已跑完一次实验，得到目标 `run_id`（可来自平台 UI 或
   `POST /api/projects/{project_id}/experiments/{experiment_id}/start` 的返回）。

## 使用内置 Action

在目标仓库放一个工作流：

```yaml
name: RAG quality gate
on:
  pull_request:

jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # …此处触发/获取你的评测 run，导出 run-id 与 experiment-id…
      - name: RAG quality gate
        uses: ./.github/actions/rag-quality-gate   # 或在同一 org 内跨仓引用
        with:
          api-base-url: ${{ vars.RAG_API_BASE_URL }}
          token: ${{ secrets.RAG_API_TOKEN }}
          project-id: ${{ vars.RAG_PROJECT_ID }}
          experiment-id: ${{ vars.RAG_EXPERIMENT_ID }}
          run-id: ${{ steps.run.outputs.run_id }}
          thresholds: |
            [
              {"metric_key": "success_rate", "min_value": 0.9},
              {"metric_key": "failure_rate", "max_value": 0.1},
              {"metric_key": "average_latency_ms", "max_value": 2000}
            ]
```

门禁通过时 job 成功并输出 `passed=true`；否则 job 失败并打印每个指标的
`PASS/FAIL (actual, reason)`，PR 检查直接变红。

## 直接调用 HTTP API（不依赖 Action）

```bash
curl -fsS -X POST \
  -H "Authorization: Bearer $RAG_API_TOKEN" \
  -H "content-type: application/json" \
  -d '{"thresholds":[{"metric_key":"success_rate","min_value":0.9}]}' \
  "$API_BASE_URL/api/projects/$PROJECT_ID/experiments/$EXPERIMENT_ID/runs/$RUN_ID/quality-gate"
```

## 设计红线（务必理解）

- **缺失即失败。** 指标从未计算（如未启用 Judge 导致 `answer_correctness` 缺失）默认
  判失败（`reason=metric_missing`），除非显式传 `missing_is_pass=true`。绝不把"没有证据"
  当作"通过"。
- **未完成不能门禁。** run 未到终态时 `incomplete=true` 且判失败，避免对半截数据放行。
- **阈值由人定、判定由机行。** Action 不承载任何评测逻辑，阈值与结论都来自服务端，保证
  同一改动在任何入口得到一致结论。
