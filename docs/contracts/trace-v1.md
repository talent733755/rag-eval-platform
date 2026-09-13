# Trace v1

Trace v1 records a run item and a bounded ordered list of named stages. Each
stage stores a SHA-256 payload hash and may store a bounded diagnostic payload;
large payloads belong in BlobStore and are referenced by a safe hash/key rather
than embedded in the database response. Stage names are unique and records are
immutable after successful write.

Only `minimal` and `full` traces are user-visible levels. Prompts, source
document全文, authorization headers, API keys and raw upstream errors must be
redacted or omitted. Queries are tenant-scoped and size-bounded. A trace is
linked to one run item and its adapter/model snapshots, so changing a later
configuration cannot change historical diagnostics.
