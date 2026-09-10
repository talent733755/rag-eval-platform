# Document Ingestion Contract v1

Status: proposed public contract for the first ingestion vertical.

This contract is versioned independently from the web application. The first
implementation establishes durable state and provenance; it intentionally does
not expose upload routes, a blob store, parsers, or a worker process yet.

## Scope and limits

The initial capability accepts PDF, DOCX, Markdown, and plain text. Defaults
are deliberately bounded and are configurable only within the server's safe
upper bounds:

| Limit | Default |
| --- | ---: |
| Uploaded bytes | 50 MiB |
| Parsed pages/sections | 10,000 |
| Normalized characters per version | 200,000 |
| Worker batch size | 10 jobs |
| Lease TTL | 60 seconds |

Filenames are display metadata, never storage paths. Original bytes and parsed
content are separate records. No model provider is called unless a provider is
explicitly configured.

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
| `checksum_mismatch` | Stored bytes do not match the declared digest | no |
| `parse_failed` | Parser rejected or could not safely normalize input | depends |
| `provider_not_configured` | Candidate provider is intentionally disabled | no; `blocked` |
| `provider_timeout` | Provider exceeded the bounded timeout | yes |
| `provider_invalid_output` | Provider output failed the candidate schema | no |
| `cancelled` | User or shutdown cancellation was observed | no |
| `lease_lost` | Fencing token or lease was stale | yes, after re-claim |
| `idempotency_conflict` | Same key was reused with another request fingerprint | no |
| `duplicate_document` | Create request matches existing project content | no |

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
