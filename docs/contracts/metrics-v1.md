# Metrics v1

Retrieval metrics are pure, deterministic functions over a bounded ordered
retrieval list and a set of relevant IDs. Duplicate retrieved IDs are counted
once and the first occurrence keeps its rank. `Recall@K`, `Precision@K`,
`HitRate@K`, `MRR`, and `nDCG@K` are bounded to `[0, 1]` when defined.

An empty relevant set is not a perfect score: recall, hit rate, MRR and nDCG
return a missing value with an explicit reason. An empty retrieved list makes
precision missing. A non-empty relevant set with no hit returns zero. Stored
results must include metric name, metric version, sample count and provenance;
changing a metric definition requires a new version and does not rewrite old
results.

## Persisted results

`metric_definitions` is project-scoped and uniquely identifies a definition by
`metric_key` and `version`. Definitions are append-only. `metric_results` stores
one `scope=run` aggregate and zero or more `scope=sample` rows for each
completed Run. Each row records `value`, optional `numerator`/`denominator`,
`sample_count`, dimensions, a distribution summary, and provenance. A missing
value must carry `missing_reason`; it is not converted to zero.

The initial `metrics-v1` calculator provides success, failure, completion,
non-empty-answer, Trace coverage, latency and token engineering metrics.
Retrieval metrics (`recall@5`, `precision@5`, `hit_rate@5`, `mrr`, `ndcg@5`) are
computed when the run item's persisted trace carries structured retrieval
evidence per the [`adapter-v2`](adapter-v2.md) `ids` convention and the
candidate item has gold evidence chunk ids to join against. When the trace has
no structured retrieval stage, the metric is missing with
`retrieval_evidence_unavailable`; when the candidate has no gold evidence, it is
missing with `no_relevant_evidence`. Recalculating a completed Run is
idempotent: an existing `(run_id, scope_key, metric_definition_id)` result is
never updated or deleted.
