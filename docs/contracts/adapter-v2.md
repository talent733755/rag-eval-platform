# Adapter v2

`adapter-v2` is a **backward-compatible superset** of [`adapter-v1`](adapter-v1.md).
It keeps the identical request/response wire shape (`AdapterRequest`, `AdapterResponse`,
citations, usage, error codes, timeouts, redaction). The only addition is a *stable
convention* for where retrieval evidence lives inside the trace, so the platform can
compute retrieval metrics (`recall@5`, `precision@5`, `hit_rate@5`, `MRR`, `nDCG@5`)
and attribute `retrieval_miss` failures deterministically.

An adapter that does not emit this convention is still valid: retrieval metrics are
then reported as `retrieval_evidence_unavailable` and no retrieval-miss diagnosis is
inferred. The platform never fabricates retrieval values from missing evidence.

## Structured retrieval trace stages

The `adapter-v1` trace stores stages as a free-form `dict[str, dict]` in
`AdapterResponse.trace.stages`. Under `adapter-v2`, an adapter that performs retrieval
MUST record the final ordered list of candidate chunk ids it handed to the generator
under the `ids` key of a retrieval-bearing stage:

```json
{
  "trace_id": "trace-...",
  "level": "minimal",
  "stages": {
    "retrieve": { "ids": ["chunk-id-a", "chunk-id-b", "chunk-id-c"] }
  }
}
```

Contract rules:

* `ids` is an **ordered** list of chunk identifier strings, ranked best-first. The
  order is significant: `precision@k`, `MRR` and `nDCG@k` depend on it.
* The canonical stage names are `retrieve` and `rerank`. If both are present, the
  **last** one wins, because it reflects the final candidate ordering after reranking.
  Earlier retrieval stages are preserved for diagnostics but do not drive metrics.
* Chunk ids are matched against the candidate item's gold evidence chunk ids
  (`CandidateItemEvidence.chunk_id`, compared as strings). The pipeline is responsible
  for emitting ids that are joinable to the ingested document chunks it was built over.
* `ids` must NOT contain document text, prompts, credentials or other private content;
  it carries identifiers only and survives standard trace redaction.
* `ids` is bounded by the trace stage payload limit (64 KiB inline); a pipeline that
  returns more candidates than fits should keep the top-ranked prefix.

## Versioning and migration

* `adapter-v2` introduces **no** new required fields and **no** changed semantics for
  existing fields, so an `adapter-v1` implementation is a valid `adapter-v2`
  implementation that simply does not expose retrieval evidence.
* Adapters opt in by setting their configuration `adapter_version` to `adapter-v2` and
  emitting the `ids` convention above. The platform reads retrieval evidence from the
  trace regardless of the declared version label; the label is documentation of intent.
* Removing the `ids` key, changing its type, or repurposing a canonical stage name is a
  breaking change and requires a new capability version.

## Failure attribution

When a run item succeeds but the gold evidence chunk ids are known and the emitted
`ids` list is non-empty yet contains none of them, the platform records a
`retrieval_miss` failure case (non-retryable, safe message "标准证据未被召回。").
When `ids` is absent or empty the platform records nothing, because retrieval cannot be
blamed without evidence.
