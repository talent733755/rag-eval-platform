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

The API exposes tenant-scoped Trace and failure lists with bounded limits. Trace
stages are redacted before persistence; inline payloads are limited to 64 KiB,
and larger payloads are written to BlobStore as an opaque reference when the
configured store accepts them. Trace and failure rows are append-only and
database-protected against update/delete. Failure cases retain only a stable
classification, retryability, safe message, attempt number, and optional Trace
ID; upstream error text is never returned.
