# Document Ingestion Architecture

## Purpose

Document ingestion is an asynchronous, tenant-scoped pipeline for turning
user-owned document bytes into traceable parsed chunks and reviewable candidate
data. PostgreSQL is the source of truth for state, provenance, idempotency, and
leases. Redis may later provide wake-up hints; it must never be used as the
durable queue.

## Current phase boundary

This phase provides the public contract, safe runtime configuration, SQLAlchemy
models, the `0002_document_ingestion`/`0003_ingestion_contract_hardening`
migrations, pure job-domain rules, a private local BlobStore, and bounded
format parsers. It deliberately does not implement:

- HTTP routes or multipart handling;
- a worker process or Compose worker service;
- object-storage adapters;
- provider calls or fabricated parse/candidate results.

Routes and workers must consume the v1 contract rather than reaching through
these tables with ad-hoc status strings.

## BlobStore boundary

`rag_eval_api.storage.protocol.BlobStore` exposes the upload/read/delete
operations plus `iter_objects` for maintenance. `LocalBlobStore` stores
generated opaque keys under an absolute private root. It writes into a
same-directory `0600` temp file, hashes and bounds the stream, fsyncs, then
publishes with a no-overwrite hard-link operation. A key is accepted only when
it matches the generated two-level grammar; path traversal, absolute paths,
symlink resolution, and missing blobs fail closed. Enumeration returns only
published regular objects with UTC metadata and skips temporary or malformed
entries. The root is never mounted as a public static path.

The reconciliation service compares enumerated objects with committed
`document_versions.storage_key` values. It applies a grace period before
deleting an unreferenced object, which covers a process crash between blob
publication and database commit. The service reports missing/deletion-failure
counters and leaves failures for a later pass; a durable worker or scheduled
maintenance command is responsible for invoking it.

The blob store returns metadata, not a user filename or filesystem path. Future
S3-compatible backends must preserve the no-overwrite, checksum, size, cleanup,
and redacted-log semantics of this contract.

## Parser boundary

`ParserRegistry` performs extension/MIME/signature allowlisting and reads a
bounded byte stream before dispatching to the versioned PDF, DOCX, Markdown,
or UTF-8 text parser. The parser output is `ParseResult` with raw content hash,
parser version, page/paragraph counts, and contiguous `CanonicalChunk` values.
Each chunk has canonical content, content hash, character/token counts, heading,
ordinal, and a JSON-safe source location (`page`, `paragraph`, `line`, and
optional `part`). The normalized output is deterministic and contains no input
path or original filename.

PDF limits are page count, object count, decoded stream bytes, recursion depth
and object count, normalized characters, and wall clock. DOCX limits are ZIP
entries, aggregate uncompressed bytes, compression ratio, XML nesting, and
normalized paragraphs/characters. ZIP absolute paths, `..` components, and
symlink entries are rejected before XML parsing. Malformed/unsupported input
is classified using the stable error taxonomy in the v1 contract. The parser
modules do not perform network I/O; production deployments must add a
non-privileged OS/container sandbox for hostile files.

`ParserRunner` is the security boundary that the next worker phase must use for
PDF/DOCX jobs. It runs a disposable subprocess and terminates its process group
on a hard timeout. Development may use a restricted fallback with Python-level
socket denial, but that is not OS network isolation. Production and
`PARSER_REQUIRE_RESOURCE_LIMITS=true` require an explicit configured,
filesystem-isolated `bwrap` profile plus CPU and memory limit support. The
executable must resolve to the root-owned, non-group/other-writable absolute
path allowlist; symlink aliases, `/usr/bin/env`, basename matches, `unshare`,
and custom launchers are rejected. The accepted token template is exact and
ordered: `bwrap --unshare-user --uid 65534 --gid 65534 --unshare-net
--unshare-pid --die-with-parent --new-session --cap-drop ALL --tmpfs /
--ro-bind /usr /usr --ro-bind /bin /bin --ro-bind /lib /lib --ro-bind /lib64
/lib64 --ro-bind /etc /etc --proc /proc --dev /dev --tmpfs /tmp --chdir /tmp
-- <parser argv>`. The runner appends read-only binds for the interpreter and
package. Runtime binds are restricted to the repository's `apps/api/.venv`
plus an exact root-owned system Python instance (`/usr`, `/usr/local`, or
`/opt/hostedtoolcache/Python/<version>/<arch>`); resolved paths, owners, and
permissions are validated. User-local Python roots and broad prefixes are
rejected. The runner then probes identity, network, resource, and host-filesystem
sentinels before accepting the profile; parser argv cannot be inserted before
the separator. Child stdout/stderr are hard-limited and the complete process
group is killed on timeout, malformed output, EOF, crash, or output overflow.
The parent/child protocol is strict UTF-8 JSON, never
pickle or another executable object format. Timeout, malformed output, EOF, and
crash outcomes retain the public `parse_timeout` and
`parser_sandbox_unavailable` error codes. The current parser runner is not a
worker process and does not complete upload-to-parse workflow.

The child output budget is explicit `MAX_PARSER_OUTPUT_BYTES` configuration
(64 MiB by default, with a 1 MiB–256 MiB bound) and is reserved for serialized
JSON rather than inferred from normalized character counts. Parser requests use
a bounded JSON stdin protocol: the parent applies the base64 expansion budget,
the child performs bounded reads under a fixed protocol ceiling, and encoded
input is checked before decoding. This prevents a child from turning malformed
or oversized protocol input into an unbounded allocation.

PDF/DOCX are always dispatched through `ParserRunner`; the direct parser
classes are not an ingestion entrypoint. `pypdf` may materialize decoded PDF
streams before a parser-level byte check, so the runner's input cap, child
`RLIMIT_AS`/`RLIMIT_CPU` (when supported), output cap, and parent hard timeout
are the required resource boundary. A platform that cannot provide the
required strict limits fails closed instead of claiming streaming protection.
The parent starts a new process group and cleans that group on failure; it does
not claim it can clean up a malicious descendant that deliberately calls
`setsid` outside the group. The supported sandbox templates' parent-death
behavior is the required defense for normal descendants.

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
explicit host/port allowlists. `BLOB_ROOT` is resolved through real paths and
rejects the filesystem root plus `/tmp`, `/var/tmp`, `/private/tmp`, and the
platform's `tempfile.gettempdir()` tree, including symlink aliases and
descendants.

Untrusted file execution limits, parser sandboxing, MIME/signature checks,
atomic blob writes, and redacted storage/parser observability are implemented
at the storage/parser boundary. SSRF-safe provider transport, durable worker
execution, and request-level audit wiring remain later phases. In-process parser
limits do not claim to replace OS-level memory/CPU isolation.
