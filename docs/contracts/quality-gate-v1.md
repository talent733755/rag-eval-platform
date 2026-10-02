# Quality Gate v1

`quality-gate-v1` defines the **deterministic, CI-facing** pass/fail gate over a run's
aggregate metrics. It is the decision point a pipeline uses to block a RAG change that
regresses quality below an agreed floor. The gate is a pure function of already-computed
metrics plus a caller-supplied threshold set — it computes nothing new and never mutates
state.

## Endpoint

```
POST /api/projects/{project_id}/experiments/{experiment_id}/runs/{run_id}/quality-gate
```

Request:

```json
{
  "thresholds": [
    {"metric_key": "success_rate", "min_value": 0.9},
    {"metric_key": "failure_rate", "max_value": 0.1},
    {"metric_key": "average_latency_ms", "max_value": 1000}
  ],
  "missing_is_pass": false
}
```

Each threshold must set `min_value`, `max_value`, or both. The gate reads only the run's
aggregate (`scope=run`, `scope_key=run`) metric values, keyed by `metric_key`.

Response:

```json
{
  "run_id": "…",
  "run_status": "succeeded",
  "passed": true,
  "incomplete": false,
  "checks": [
    {"metric_key": "success_rate", "passed": true, "actual": 1.0,
     "min_value": 0.9, "max_value": null, "reason": "ok"}
  ]
}
```

## Red lines

* **Never silently pass.** A metric that is missing (never computed, unavailable) fails
  by default (`reason: metric_missing`). A deployment may opt into `missing_is_pass:
  true`, but absence of evidence is never treated as success unless explicitly allowed.
* **An incomplete run cannot gate.** A run whose status is not `succeeded`/`failed` is
  reported `incomplete: true` and fails every check (`reason: run_incomplete`), so CI
  cannot gate on partial data.
* **Deterministic and auditable.** Every check records the actual value, the bound, and a
  stable machine-readable `reason` (`ok`, `below_min`, `above_max`, `metric_missing`,
  `metric_missing_tolerated`, `run_incomplete`). The verdict is reproducible from the
  same metrics + thresholds.
* **Member-scoped.** Any project member may read a gate verdict; no mutation is exposed.

## Reason codes

| Reason | Meaning |
| --- | --- |
| `ok` | Metric present and within bounds. |
| `below_min` | `actual < min_value`. |
| `above_max` | `actual > max_value`. |
| `metric_missing` | No aggregate value for the key and `missing_is_pass=false`. |
| `metric_missing_tolerated` | Missing but `missing_is_pass=true`. |
| `run_incomplete` | Run has not reached a terminal status. |

## GitHub Action

A thin composite Action (`.github/actions/rag-quality-gate/action.yml`) wraps the
endpoint: it polls the run until terminal, POSTs the thresholds, and exits non-zero when
`passed` is false. The Action carries no evaluation logic — all thresholds and the
verdict live server-side, so the same gate is reused across local checks, CI, and any
other client.
