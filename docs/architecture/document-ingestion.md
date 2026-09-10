# Document Ingestion Architecture

## Purpose

Document ingestion is an asynchronous, tenant-scoped pipeline for turning
user-owned document bytes into traceable parsed chunks and reviewable candidate
data. PostgreSQL is the source of truth for state, provenance, idempotency, and
leases. Redis may later provide wake-up hints; it must never be used as the
durable queue.

## Current phase boundary

This phase provides the public contract, safe runtime configuration, SQLAlchemy
models, the `0002_document_ingestion` migration, and pure job-domain rules.
It deliberately does not implement:

- HTTP routes or multipart handling;
- BlobStore or local/object-storage adapters;
- PDF/DOCX/Markdown/TXT parsers;
- a worker process or Compose worker service;
- provider calls or fabricated parse/candidate results.

Those components must consume the v1 contract rather than reaching through
these tables with ad-hoc status strings.

## Logical flow

```text
authorized request
      │  tenant + idempotency fingerprint
      ▼
documents ──> document_versions ──> ingestion_jobs(parse)
                                      │
                                      ▼
                              document_chunks (immutable)
                                      │
                         explicit capability negotiation
                                      ▼
candidate_datasets ──> generation_config ──> ingestion_jobs(generate)
                                      │
                                      ▼
                    candidate_items ──> candidate_item_evidence
```

The job row records the current state and counters. Each execution creates one
append-only `ingestion_job_attempts` final-history row. The current execution
uses one mutable `ingestion_job_leases` row. A monotonically increasing fencing
token is checked on every future side-effect write; a stale worker may report a
discarded outcome but cannot commit chunks or candidates.

## Persistence boundaries

`documents.latest_version_id` is nullable while the first version is created.
Migration `0002` creates `documents`, then `document_versions`, then the rest
of the graph, and adds the latest-version foreign key only after both sides
exist. `0001_foundation` is not modified. Source versions, chunks, candidate
evidence, and final attempt history use `RESTRICT` or append-only boundaries;
leases are the intentionally mutable exception.

Every child table stores `organization_id` and `project_id` and has a composite
foreign key to its tenant parent. This is defense in depth: application
authorization remains required, while the database prevents accidental
cross-project links in transactions and fixtures.

## Domain service boundary

`rag_eval_api.services.ingestion_jobs` is a dependency-free policy module.
Repositories and workers must call it for:

- the explicit transition graph;
- retry eligibility (`failed`/`partial` only when retryable, or explicit
  configuration resolution from `blocked`);
- cancellation and blocking;
- same-key/same-fingerprint replay versus idempotency conflict;
- lease claim, heartbeat, expiry, and fencing-token validation.

The in-memory `LeaseManager` is a deterministic unit-test authority, not a
production queue. A PostgreSQL implementation must use a row lock and a
conditional update that includes the current fencing token.

## Security and configuration

`Settings` provides bounded upload/parser limits, private blob root, worker
lease intervals, and opt-in provider configuration. Secrets use `SecretStr`
and are not included in safe configuration output. Production rejects relative
or temporary blob roots, wildcard provider host allowlists, development actor
configuration, non-HTTPS provider URLs, and provider configuration without
explicit host/port allowlists.

Untrusted file execution limits, parser sandboxing, MIME/signature checks,
atomic blob writes, SSRF-safe provider transport, and redacted observability
belong to the later adapter/parser/worker phases and are required before those
components are considered complete.
