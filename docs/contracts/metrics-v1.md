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
