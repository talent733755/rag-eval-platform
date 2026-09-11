# Document Ingestion Contract v1

Status: proposed public contract for the first ingestion vertical.

This contract is versioned independently from the web application. The current
implementation establishes durable state, a private local BlobStore, and
deterministic parser output. HTTP upload routes and the durable worker are later
adapters and must consume these contracts without inventing a second format.

## Scope and limits

The initial capability accepts PDF, DOCX, Markdown, and plain text. Defaults
are deliberately bounded and are configurable only within the server's safe
upper bounds:

| Limit | Default |
| --- | ---: |
| Uploaded bytes | 50 MiB |
| Parsed pages/sections | 10,000 |
| Normalized characters per version | 200,000 |
| Normalized paragraphs per version | 100,000 |
| Canonical chunk characters | 2,000 |
| PDF parser wall clock | 10 seconds |
| PDF object count | 100,000 |
| PDF decoded stream bytes | 100 MiB |
| PDF recursion depth | 100 |
| PDF recursion objects | 100,000 |
| DOCX ZIP entries | 10,000 |
| DOCX uncompressed bytes | 100 MiB |
| DOCX compression ratio | 100:1 |
| DOCX XML nesting depth | 100 |
| Parser child serialized output | 64 MiB |
| Worker batch size | 10 jobs |
| Lease TTL | 60 seconds |

Filenames are display metadata, never storage paths. Original bytes and parsed
content are separate records. No model provider is called unless a provider is
explicitly configured. Parser input is treated as hostile and is never fetched
from the network.

## BlobStore contract

`BlobStore` is the only boundary allowed to persist uploaded bytes. The initial
backend is `LocalBlobStore`, rooted at the absolute private `BLOB_ROOT`. It
returns an opaque two-level storage key generated with cryptographic randomness;
the user filename is never included in that key. The API must not serve the
blob root directly.

The local backend streams into a `0600` temporary file, enforces the hard byte
limit while reading, computes SHA-256, fsyncs, and publishes with an atomic
no-overwrite operation in the same filesystem. Temporary files are removed on
success, checksum/size failure, exception, cancellation, and process cleanup.
`open`, `exists`, and `delete` reject absolute keys, traversal, malformed keys,
symlinked directories/files, and missing blobs. Storage logs include only safe
metadata such as size and digest; they never include local paths, filenames, or
secrets. Object storage can be added later behind the same protocol.

## Parser contract

`ParserRegistry` accepts only `.pdf`, `.docx`, `.md`/`.markdown`, and `.txt`.
The extension, declared MIME (when supplied), and content signature must agree.
Unsupported input is `unsupported_type`; a validly identified but malformed
document is `parse_failed`; a decoded size, page, paragraph, ZIP, XML, object,
or stream limit is `size_exceeded`. A parser wall-clock deadline is
`parse_timeout`; inability to start the required parser sandbox is
`parser_sandbox_unavailable`.

Each parser returns a `ParseResult`:

```json
{
  "parser_version": "markdown-v1",
  "content_hash": "64 lowercase hex characters",
  "byte_size": 123,
  "page_count": 0,
  "paragraph_count": 2,
  "chunks": [{
    "ordinal": 0,
    "content": "normalized text",
    "content_hash": "64 lowercase hex characters",
    "character_count": 15,
    "token_count": 3,
    "heading": "Section title",
    "source_location": {"line": 3}
  }]
}
```

Normalization is UTF-8-only, Unicode NFKC, newline-stable, and deterministic.
Chunk hashes are SHA-256 of canonical UTF-8 content. PDF chunks carry `page`,
DOCX chunks carry `paragraph`, and Markdown chunks carry `line`; chunking adds
`part` when one source block exceeds the configured chunk bound. Empty blocks
are omitted, ordinals are contiguous, and no original filename is copied into
the output.

PDF parsing bounds page count, object count, decoded stream bytes, recursion
depth/object count, decoded normalized characters, and wall-clock checks
between pages. DOCX parsing validates the ZIP before `python-docx`:
absolute paths, `..` components, symlink entries, entry count, aggregate
uncompressed bytes, compression ratio, and XML nesting depth are rejected.
The built-ins do not resolve external entities or perform network requests.
Deployments processing untrusted files must additionally run the API/parser in
a non-privileged, resource-limited container or equivalent sandbox; the
in-process parser is not a substitute for OS-level isolation.

The public registry uses `ParserRunner` for PDF and DOCX by default. In
development, the runner may use a disposable process fallback with process
limits where available and Python-level socket denial; this fallback is not OS
network isolation. Production and `PARSER_REQUIRE_RESOURCE_LIMITS=true` require
an explicit `PARSER_SANDBOX_EXECUTABLE` plus configured arguments that enforce
non-root, no-network, CPU, memory, and filesystem limits. Only the supported
filesystem-isolated `bwrap` profile is accepted, with this exact ordered
template (the runner appends read-only binds for the interpreter/package):
`bwrap --unshare-user --uid 65534 --gid 65534 --unshare-net --unshare-pid
--die-with-parent --new-session --cap-drop ALL --tmpfs / --ro-bind /usr /usr
--ro-bind /bin /bin --ro-bind /lib /lib --ro-bind /lib64 /lib64 --ro-bind /etc
/etc --proc /proc --dev /dev --tmpfs /tmp --chdir /tmp -- <parser argv>`.
`unshare`, `/usr/bin/env`, extra flags, reordered flags, and parser arguments
before the separator are rejected. The executable must be an absolute real
path in the root-owned, non-group/other-writable allowlist; basename matches
and symlink aliases are rejected, and the exact template is probed against
identity, network, resource, and host-filesystem sentinels before use. Child
stdout and stderr are each hard-limited; overflow
maps to `parser_sandbox_unavailable` after the complete process group is
terminated. If those capabilities are
unavailable, settings fail closed. The child protocol is strict UTF-8 JSON with
an `{"kind":"ok","result":...}` or
`{"kind":"error","code":...,"message":...}` envelope. The parent never
deserializes executable object formats; malformed, duplicate-key, invalid
UTF-8, EOF, or crashed output maps to `parser_sandbox_unavailable`. Hard
timeouts terminate the process group and map to `parse_timeout`. This runner
is the parser boundary for the next worker phase; it does not itself implement
a worker, upload route, or upload-to-parse workflow.

The serialized child-output budget is explicit configuration
`MAX_PARSER_OUTPUT_BYTES`, defaulting to 64 MiB and bounded to 1 MiB–256 MiB.
It is independent from the normalized-character limit so a valid result with
many small chunks is not rejected by a character-only estimate. The JSON
request sent over stdin is also bounded: the parent rejects requests larger
than the base64 input budget plus 64 KiB metadata. The input budget is derived
from the 64 MiB maximum parser input (`MAX_MAX_PARSER_INPUT_BYTES`) and the
base64 expansion, so it is bounded to roughly 85 MiB on the wire. The child
checks the encoded input budget before base64 decoding and checks the decoded
byte count afterward.

PDF and DOCX always use this runner, even when text parsers are used in a
non-isolated unit-test mode. Because `pypdf` can materialize a decoded stream
before its parser-level check, safety depends on the runner input cap, child
`RLIMIT_AS`/`RLIMIT_CPU` where supported, bounded output, and parent hard
timeout. Unsupported resource controls fail closed in strict mode; no
streaming-decompression guarantee is made for direct parser classes.
The parent cleans its process group but does not claim to recover descendants
that deliberately call `setsid`; the supported sandbox parent-death behavior
is the required defense for normal descendants.

## Tenant and resource identity

Every resource has `organization_id` and `project_id`. Database relationships
carry the pair as a composite key, so a valid UUID from another project cannot
be attached by changing only the resource ID. Cross-project reads and writes
fail closed.

- A logical document is identified by `documents.id`.
- Upload identity is `(project_id, idempotency_key)` for request replay.
- Content identity is `(project_id, sha256, byte_size)`; content never silently
  replaces an existing logical document.
- `document_versions` are immutable byte metadata plus parse outcome metadata.
- Chunks are immutable and retain their source version, ordinal, hash, and
  source location.
- Candidate evidence points to a chunk and carries the same tenant pair.
- A source version referenced by a candidate item remains recoverable. Archive
  removes it from active lists; physical blob garbage collection is a separate
  retention operation and must not delete referenced versions.

## Canonical records

All timestamps are UTC RFC 3339 values. All IDs are UUIDs.

```json
{
  "document": {
    "id": "uuid",
    "organization_id": "uuid",
    "project_id": "uuid",
    "display_name": "handbook.pdf",
    "source_type": "pdf",
    "latest_version_id": "uuid|null",
    "archived_at": "timestamp|null"
  },
  "document_version": {
    "id": "uuid",
    "document_id": "uuid",
    "version_number": 1,
    "sha256": "64 lowercase hex characters",
    "byte_size": 12345,
    "detected_mime": "application/pdf",
    "storage_key": "opaque/private/key",
    "parse_status": "queued",
    "parser_version": "parser-v1|null",
    "parse_error_code": "string|null"
  },
  "chunk": {
    "id": "uuid",
    "document_version_id": "uuid",
    "ordinal": 0,
    "content": "normalized text",
    "content_hash": "64 lowercase hex characters",
    "source_location": {"page": 1, "paragraph": 3},
    "character_count": 15,
    "token_count": 4
  }
}
```

## Job states and transitions

`ingestion_jobs.status` is the durable source of truth:

```text
queued ──> processing ──> succeeded
   │              ├──────> partial
   │              ├──────> failed
   │              ├──────> blocked
   │              └──────> cancelled
   └────────────────────> cancelled

blocked ──(valid configuration/retry)──> queued
failed/partial ──(retryable retry)─────> queued
```

`succeeded`, `partial`, `failed`, and `cancelled` are terminal outcomes for
the current job. Retry creates a new attempt and does not rewrite an earlier
attempt. `blocked` does not consume a worker retry loop: it is used for a
missing capability or configuration and moves to `queued` only after an
explicit valid retry/configuration action. Cancellation is accepted from
`queued`, `processing`, and `blocked`; a worker must re-check cancellation
before every side effect.

`document_versions.parse_status` mirrors the parse subset (`queued`,
`processing`, `succeeded`, `failed`, `cancelled`) and is not a substitute for
the job history.

## Error taxonomy

Error codes are stable machine-readable identifiers. Messages are bounded,
redacted, and safe to show to an operator.

| Code | Meaning | Retryable |
| --- | --- | --- |
| `unsupported_type` | Extension/signature/MIME is not allowlisted | no |
| `size_exceeded` | Upload or decoded content exceeds a configured bound | no |
| `parse_timeout` | Parser exceeded its wall-clock deadline | yes |
| `parser_sandbox_unavailable` | Required parser sandbox could not be started or exited unexpectedly | depends |
| `checksum_mismatch` | Stored bytes do not match the declared digest | no |
| `parse_failed` | Parser rejected or could not safely normalize input | depends |
| `security_violation` | Parser or storage boundary rejected an unsafe input or path | no |
| `provider_not_configured` | Candidate provider is intentionally disabled | no; `blocked` |
| `provider_timeout` | Provider exceeded the bounded timeout | yes |
| `provider_invalid_output` | Provider output failed the candidate schema | no |
| `cancelled` | User or shutdown cancellation was observed | no |
| `lease_lost` | Fencing token or lease was stale | yes, after re-claim |
| `idempotency_conflict` | Same key was reused with another request fingerprint | no |
| `duplicate_document` | Create request matches existing project content | no |
| `invalid_storage_key` | Blob key is not an opaque key generated by BlobStore | no |
| `blob_not_found` | Requested blob is absent | no |
| `blob_already_exists` | Atomic blob publication found an existing destination | no |
| `blob_security_error` | BlobStore could not safely access its private boundary | no |
| `blob_store_error` | Unclassified BlobStore failure; operators must inspect redacted logs | depends |

Raw provider responses, credentials, local paths, and unbounded parser
tracebacks are never returned or written to normal logs.

## Idempotency

The create-document request uses `(project_id, idempotency_key)` as its replay
scope. Retry and generation operations use the unique scope
`(project_id, operation_kind, idempotency_key)`. Every request stores a
canonical request fingerprint:

- Same scope and same fingerprint returns the original job/attempt result.
- Same scope and a different fingerprint returns `409 idempotency_conflict`.
- A new retry never mutates the prior attempt row.
- A create request with identical `(project_id, sha256, byte_size)` returns
  `409 duplicate_document` with the existing document/version IDs; it never
  creates a second logical document silently.
- The explicit version route may create a new version only for a caller that
  already selected the logical document ID.

## Candidate generation envelope

Candidate generation is a capability-negotiated, opt-in contract. The first
supported capability is `candidate-generation/v1`:

```json
{
  "capability_version": "candidate-generation/v1",
  "request_id": "uuid-or-provider-request-id",
  "input": {
    "project_id": "uuid",
    "document_version_ids": ["uuid"],
    "chunk_content_hashes": ["sha256"],
    "contexts": [{"chunk_id": "uuid", "ordinal": 0, "text": "bounded text"}]
  },
  "provider": {"name": "provider-name", "model": "model-name"},
  "generation_config": {
    "prompt_version": "prompt-v1",
    "randomness": 0,
    "seed": 7
  },
  "candidates": [{
    "question": "...",
    "question_type": "single_answer",
    "difficulty": "medium",
    "reference_answer": "...",
    "confidence": 0.8,
    "evidence": [{"chunk_id": "uuid", "ordinal": 0, "excerpt": "..."}],
    "automatic_checks": {"schema_valid": true}
  }],
  "usage": {"input_tokens": 0, "output_tokens": 0},
  "estimated_cost": 0,
  "actual_cost": 0,
  "error": null
}
```

The generator must reject an unsupported capability before enqueueing a job.
Contexts are bounded and carry hashes; the provider output is schema-validated
and is never treated as published truth. `candidate_generation_configs` stores
the exact capability, provider/model, prompt/check versions, requested version
IDs, chunk hashes, environment metadata, request ID, usage, and cost snapshot.

## Authorization and audit

The existing project roles apply to ingestion:

| Action | Viewer | Editor | Admin |
| --- | ---: | ---: | ---: |
| List/inspect documents and versions | yes | yes | yes |
| Upload/version/retry parse | no | yes | yes |
| Start candidate generation | no | yes | yes |
| Cancel own permitted job | no | yes | yes |
| Archive/delete document | no | no | yes |
| Change provider/retention configuration | no | no | yes |

Every mutation records an audit event with actor, tenant, action, resource ID,
request ID, and a redacted metadata snapshot. Provider keys and raw document
content are excluded from audit metadata. Published-reference protections
apply to every role.

## Compatibility

Adding optional fields is backward compatible. New states, error codes, or
capability versions require a contract revision and client compatibility note.
Changing meaning, tenant scope, identity, or the transition graph is a
breaking change and requires a new `v2` contract plus a migration document.
