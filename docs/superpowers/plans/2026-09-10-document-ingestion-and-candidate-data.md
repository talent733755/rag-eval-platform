# Document Ingestion and Candidate Evaluation Data Implementation Plan

> **Status:** Approved implementation plan; execution in progress. The current branch has completed the foundation, persistence, BlobStore, parser, and integration-gate slices. HTTP API, worker, candidate generation, and Documents UI remain subsequent slices in this plan.

## Goal

Implement the first real business vertical of RAG Eval Platform: upload supported knowledge documents, persist immutable document versions, parse them into traceable chunks, and create candidate evaluation data through a versioned generation contract. The flow must be safe, observable, retryable, and usable from the existing admin shell; it must not silently fabricate evaluation data or overwrite source documents.

## Scope and boundaries

This plan covers:

1. A versioned public contract for documents, document versions, chunks, candidate items, and generation jobs.
2. Tenant/project-scoped persistence and audit events.
3. Safe local blob storage behind an interface, with an explicit path for an object-storage backend later.
4. PDF, DOCX, Markdown, and TXT parsing with bounded resources and source-location metadata.
5. A real local worker process, durable job attempts, leases, crash recovery, cancellation, retry, and failure classification.
6. HTTP APIs and the Documents page needed to upload, inspect, retry, and start candidate generation.
7. Deterministic tests using local fixtures; no external model or provider calls in CI.

This plan does not implement review workflows, Gold Dataset publishing, Adapter execution, experiments, metrics, or Trace storage. Candidate records remain draft/reviewable data; publishing is the next follow-up plan. A candidate generator is a public provider interface. The first implementation includes an OpenAI-compatible provider only when explicitly configured and never uses credentials or external calls by default. The local worker and a deterministic development actor/seed fixture are included so the upload-to-parse state machine is runnable even though production authentication remains a later plan.

## Non-negotiable design rules

- Every record is scoped by `organization_id` and `project_id`; cross-project access must fail closed.
- Original bytes are immutable. Re-uploading the same logical document creates a new version; it never overwrites history.
- Files are accepted by allowlisted extension plus detected content type, size limit, checksum, and parser capability. User-supplied filenames never become filesystem paths.
- Parsing and generation are asynchronous domain jobs with explicit states: `queued`, `processing`, `blocked`, `succeeded`, `partial`, `failed`, `cancelled`. `blocked` is terminal until an explicit configuration/retry action; `provider_not_configured` never loops in the worker.
- State transitions are validated and audited. Retry creates an immutable `ingestion_job_attempts` row while preserving every prior failure, error code, configuration snapshot, and timing record.
- All external calls have bounded timeouts, retryable-error classification, cancellation, redacted logs, and no credentials in responses.
- Generated candidate JSON is schema-validated. Invalid provider output is a classified failure, never silently coerced into a candidate.
- Public API schemas and status values are documented, tested, and versioned. Breaking changes require a migration note.
- Every test and local command must work without an external model provider or network dependency. Candidate generation without an explicitly configured provider remains queued/blocked with an honest `provider_not_configured` error; it is never replaced by fake generated content.

## Public contracts

Add `docs/contracts/document-ingestion-v1.md` containing:

- Supported formats and limits (initial defaults: 50 MiB per upload, 10,000 pages/sections, 200,000 normalized characters per parsed version; all configurable with safe upper bounds).
- Canonical document, source-location, chunk, candidate-item, and job schemas.
- Status transition diagrams and error codes (`unsupported_type`, `size_exceeded`, `checksum_mismatch`, `parse_failed`, `provider_not_configured`, `provider_timeout`, `provider_invalid_output`, `cancelled`, etc.). `blocked` jobs do not consume attempts and only move to `queued` after a valid configuration/retry request.
- Idempotency rules for upload and retry requests, including the request fingerprint, conflict response, and replay response.
- Versioned `CandidateGenerator` envelope: `capability_version`, input document-version/chunk hashes and bounded context, provider/model metadata, generation config, output candidates, automatic checks, usage/cost, request ID, and error taxonomy. Capability negotiation must reject unsupported versions before a job is enqueued.
- Redaction and data-sharing behavior for configured model providers.
- Compatibility/versioning policy and example API payloads.

Add `docs/architecture/document-ingestion.md` with the storage, parser, job, audit, and data-lineage flow. Update README with a minimal local-file example and an explicit statement that model calls are opt-in.

The contract must also define these exact rules:

- Upload identity is `(project_id, idempotency_key)` for request replay; content identity is `(project_id, sha256, byte_size)` and never silently replaces a logical document.
- A logical document is identified by its UUID. `POST /documents` creates a logical document; `POST /documents/{document_id}/versions` creates a new version. Re-uploading identical content through the create route returns `409 duplicate_document` with the existing document/version IDs; it never silently creates a second logical document. Uploading through the version route may create a new version only with an explicit document ID.
- Every retry request carries `Idempotency-Key` and a canonical request fingerprint. The unique scope is `(project_id, operation_kind, idempotency_key)`. Replaying the same fingerprint returns the original job/attempt response; reusing a key with a different fingerprint returns `409 idempotency_conflict`.
- A document version remains recoverable while any candidate item or future published dataset version references it. Archive removes it from active lists; physical blob deletion is a separate retention/garbage-collection operation and is disabled for referenced versions.
- Pagination uses an opaque cursor over `(updated_at, id)` with a fixed maximum page size. Upload progress uses a cancellable `XMLHttpRequest`/fetch-stream abstraction with `AbortController`; the API exposes job progress, not an invented percentage.
- Development authentication uses a seeded fixed actor selected by `DEV_ACTOR_ID` only in `APP_ENV=development`; the API ignores arbitrary actor headers and production startup rejects this setting. `scripts/seed-dev-data.py` creates the organization/project/admin membership and is idempotent. The worker rechecks tenant scope from the job row.

## Data model and migration

Create a new Alembic migration and SQLAlchemy models for:

- `documents`: logical document identity, project/org scope, display name, source type, latest version, archived/deleted timestamps.
- `document_versions`: immutable blob metadata (checksum, byte size, detected MIME, storage key), version number, parser version, parse status/error, timestamps.
- `document_chunks`: immutable normalized content with ordinal, heading, content hash, page/paragraph location, token/character counts, and source version.
- `candidate_datasets`: project-scoped draft candidate collection and generation configuration snapshot.
- `candidate_dataset_items`: question, question type, difficulty, reference answer, confidence, automatic checks, review status, source version IDs, and provenance. Evidence is represented by `candidate_item_evidence` with `(item_id, chunk_id, organization_id, project_id, ordinal)` and a composite foreign key to `document_chunks`.
- `ingestion_jobs`: job kind enum, nullable typed resource IDs (`document_version_id` or `candidate_dataset_id`, never an unvalidated polymorphic string), status, idempotency key/fingerprint, progress counters, current attempt number, cancellation timestamp, and timestamps.
- `ingestion_job_attempts`: append-only finalized attempt history with immutable attempt number, job ID, worker ID, final status, started/finished timestamps, input/config snapshot, error code/message, retryability, and fencing token. A running attempt is not mutated in this table.
- `ingestion_job_leases`: the mutable execution row for the current attempt: job ID, attempt number, worker ID, lease expiry, heartbeat, and monotonically increasing fencing token. Every chunk/candidate/result write includes the current fencing token in its transaction predicate; an expired worker can only record a discarded/stale outcome.
- `candidate_generation_configs`: normalized provider/model/prompt/parser/normalizer/check-rule configuration snapshot, seed/randomness, requested document version IDs, chunk content hashes, environment/platform version, request IDs, token usage, and estimated/actual cost.

Use UUIDs, UTC timestamps, check constraints for enums and non-negative counters, composite tenant foreign keys, indexes for project/status/time queries, and immutable constraints for source versions and published references. Every resource relationship, including jobs, candidate evidence, source versions, and chunks, must carry or derive a composite tenant key that is checked in the database. Add audit events for upload, parse, retry, delete/archive, generation start/cancel/failure/success. Do not add a database trigger that makes legitimate job progress impossible; enforce immutable historical data at ORM and database boundaries.

Avoid a circular latest-version foreign key: `documents.latest_version_id` is nullable during migration and is populated in the same transaction as the first version; the FK is added after both tables exist. Deleting/archive uses `ON DELETE RESTRICT` for referenced versions. There is no physical blob delete in a user request; a later retention job may delete only unreferenced blobs after a documented grace period.

## Service architecture

Create explicit protocols and implementations:

- `BlobStore`: `put`, `open`, `delete`, `exists`; `LocalBlobStore` stores under a configured private root using generated keys and atomic writes. The API never serves the root directly. In Compose, API and worker mount the same named `rag_eval_blobs` volume at `/var/lib/rag-eval/blobs`, run with the same non-root UID/GID, and clean only their own temporary subdirectories.
- `DocumentParser`: format-specific parsers returning canonical sections/chunks and locations. Use pinned libraries (`pypdf`, `python-docx`, `markdown-it-py`) with licenses recorded in the dependency inventory; perform MIME/signature checks before parsing.
- `JobRepository`/state machine: one transaction for state transition, counters, lease, attempt history, error classification, and audit event. Claims use `SELECT ... FOR UPDATE SKIP LOCKED`; leases have a bounded TTL, heartbeat, and fencing token. Expired leases return to `queued` only after idempotency checks; all side-effect writes verify the fencing token.
- `IngestionWorker`: a separately runnable `python -m rag_eval_api.worker` process that polls bounded batches, claims jobs, executes parsers/generators, heartbeats, records attempts, and shuts down gracefully. Compose and README include the worker service/command. A job is never reported `succeeded` merely because it was enqueued.
- `CandidateGenerator`: versioned interface receiving bounded chunk context and returning strict candidate payloads. Provider adapters are isolated from route code.
- `OpenAICompatibleCandidateGenerator`: opt-in HTTP client for `POST {base_url}/v1/chat/completions` with a strict JSON-schema response envelope, explicit HTTPS-only base URL configuration, exact hostname and port allowlists (`RAG_EVAL_PROVIDER_ALLOWED_HOSTS`/`..._PORTS`, empty by default), redirects disabled, DNS resolution checked immediately before connection against loopback/private/link-local/reserved ranges, timeout/retry/cancel, secret redaction, provider request idempotency key, and response-schema validation. The public generator envelope defines endpoint, capability version, model, prompt/template version, bounded chunk context, generation parameters, usage/cost, and error mapping. Unit tests use a local fake transport; the API key is injected, never persisted or returned.

The worker uses Redis for wake-up/queue hints but treats PostgreSQL as the source of truth. It must tolerate duplicate wake-ups and process restarts. Do not use unbounded FastAPI background tasks for durable work.

### Untrusted file execution limits

- Stream uploads to a private temporary file with a hard byte limit before parser dispatch; reject early at reverse proxy and application layers.
- PDF parsing has page, decoded-character, recursion, and wall-clock limits. DOCX parsing has ZIP entry count, total uncompressed size, compression ratio, XML depth, and wall-clock limits. Reject symlinks and absolute ZIP paths.
- Parser subprocesses run with a bounded timeout, memory/CPU limits where the platform supports them, no network access, and a non-privileged user. If portable process isolation is unavailable, the service must fail closed in production and document the platform requirement.
- Temporary files are created with restrictive permissions, atomically renamed, and removed on success, failure, cancellation, and worker shutdown.
- Provider URLs are validated before every request and every redirect; redirects are disabled unless explicitly allowlisted. Only HTTPS is accepted outside development.

### Runtime and local-environment prerequisites

- Add pinned runtime dependencies to `apps/api/pyproject.toml`: `python-multipart==0.0.20`, `httpx==0.28.1`, `pypdf==5.4.0`, `python-docx==1.1.2`, and `markdown-it-py==3.0.0`; move `httpx` from dev to runtime, update `apps/api/uv.lock`, and verify with `uv lock --directory apps/api --check`/`uv sync --directory apps/api --locked`. Record each license in `docs/legal/dependency-licenses.md`. Keep test-only fakes and parser fixtures in the dev group.
- Add worker configuration to `config.py`/`.env.example`: private blob root, upload/parser limits, worker batch size, lease/heartbeat intervals, provider URL/key injection, and safe defaults. Production configuration must reject unsafe local blob roots, wildcard provider allowlists, and missing signing/secret settings.
- Add a Compose `worker` service and a bounded readiness/health check. `make install`, `make test`, and README commands must cover API, Web, and worker dependencies without network calls beyond package installation.
- Add a development-only actor/seed fixture for API and Playwright integration tests. It must be impossible to enable through production settings; real authentication/invitations remain the later authentication plan.
- Add a PostgreSQL integration test job/service in CI for migrations, composite constraints, leases, and audit immutability. Mark these tests with `@pytest.mark.integration`; default `make test` and API quality use `pytest -m "not integration"`, while `make test-integration` uses one `.ONESHELL:` Make recipe, creates a temporary Compose env file with `mktemp` from `.env.example` without touching an existing `.env`, disables implicit repository `.env` loading and host Compose overrides, starts `docker compose --env-file "$$COMPOSE_ENV_FILE" --profile integration up -d postgres redis`, waits with `scripts/wait-for-services.sh --compose-env-file "$$COMPOSE_ENV_FILE"`, and invokes the database helper against a private per-run env file. The recipe exports the generated database URL, runs migrations and `pytest -m integration -q`, and defines a cleanup trap that preserves the original status, reports cleanup failures, stops Compose with the same isolated environment, removes only the private temporary directory, and exits with the saved status. Unit tests may use SQLite only for pure service tests; they cannot stand in for PostgreSQL constraint behavior.

## API surface

Add tenant-scoped routes under `/api/projects/{project_id}`:

- `GET /documents` with pagination, status/type filters, and stable ordering.
- `POST /documents` multipart upload for new logical documents with `Idempotency-Key` and bounded content length; identical content returns `409 duplicate_document`.
- `POST /documents/{document_id}/versions` multipart upload for an explicitly selected logical document with `Idempotency-Key`.
- `GET /documents/{document_id}` including latest version/status/error summary.
- `GET /documents/{document_id}/versions` and `GET /documents/{document_id}/versions/{version}`.
- `POST /documents/{document_id}/versions/{version}/retry-parse` with `Idempotency-Key`, request fingerprint, and replay/conflict semantics.
- `POST /documents/{document_id}/generate-candidates` with an explicit immutable `document_version_id`, dataset name, config snapshot, `capability_version`, and `Idempotency-Key`; the request fails if the version is not parse-successful.
- `POST /api/projects/{project_id}/ingestion-jobs/{job_id}/cancel` and `GET /api/projects/{project_id}/ingestion-jobs/{job_id}`; both verify the job belongs to the project and return `404` for cross-project IDs. All frontend polling uses this exact project-scoped path.
- `DELETE /documents/{document_id}` as archive/delete with confirmation semantics and published-reference protection.

Use consistent JSON errors, `202 Accepted` for queued work, `409` for invalid transitions/conflicts, `413` for size limits, `415` for unsupported types, and `422` for invalid payloads. Every mutation must check project membership and write an audit event. Define action permissions explicitly: viewers may list and inspect versions; editors may upload, retry parsing, and start candidate generation; only admins may archive/delete documents or alter retention/provider configuration. No role may bypass a published-reference restriction.

`GET /documents` returns `{items, next_cursor, summary}`; cursors are opaque and bounded. `GET /api/projects/{project_id}/ingestion-jobs/{job_id}` is the polling contract; optional Redis/WebSocket notification is an optimization and never the source of truth. Batch upload uses repeated multipart `files` fields on the separate `POST /api/projects/{project_id}/documents/batch` endpoint with per-file result objects, allowing partial success without hiding individual failures; each file has its own idempotency suffix and job.

## Web scope

Replace the Documents placeholder with the approved page structure:

- summary cards for total documents, parsing, failed parsing, and latest versions;
- search/filter toolbar with loading, empty, no-result, error, and permission states;
- accessible table showing name, type, version, parse status/error, linked candidate dataset, and updated time;
- upload dialog with allowlist, size limit, duplicate behavior, per-file progress, cancellation, and partial-success reporting;
- row actions for detail, retry parse, generate candidates, and archive with confirmation;
- project query context preserved in every action link and mutation.

Do not expose raw storage paths, provider keys, or unredacted parser errors. Use the existing design tokens, status badges, empty-state conventions, and permission map. Preserve `project`, `q`, `type`, `status`, and cursor query context across refresh, detail, retry, archive, and return-to-list navigation; reset the cursor when the search/filter changes. Tables must use real header/cell semantics, labeled controls, `aria-live` for job updates, visible focus, contrast-compliant statuses, and a reduced-motion path.

The upload client must use a dedicated multipart transport with `AbortController`, progress callbacks, bounded client-side file validation, and typed per-file results. It must not force multipart through the existing JSON-only client or claim a completed parse before polling the job resource.

## Test-first implementation sequence

1. Write contract/status transition and parser fixture tests; verify they fail.
2. Add migration/models and tenant/immutability tests.
3. Add blob store security tests: traversal, overwrite, size, checksum, atomic write, and cleanup.
4. Implement parsers and bounded normalization; test PDF/DOCX/Markdown/TXT fixtures, malformed files, and location metadata.
5. Implement job state machine, cancellation, retry classification, and audit behavior.
6. Implement API routes with API-level authorization, pagination, idempotency, and error contract tests.
7. Implement the opt-in candidate generator contract with fake transport tests; verify capability negotiation, successful item/evidence/config persistence, invalid output, provider timeout, request idempotency, and provider-not-configured blocking behavior.
8. Implement Documents UI and component tests for all required states and mutation feedback.
9. Add a PostgreSQL-backed API integration fixture/job in CI; verify migrations, composite tenant constraints, lease recovery, and audit immutability. Add the worker and Compose startup/readiness check.
10. Add Playwright coverage for upload → queued parse → failed/retry state, cancellation, partial multi-file upload, permission differences, and 320px keyboard/focus behavior using deterministic local API fixtures; do not call a real provider.
11. Run OpenAPI generation, API/web tests, lint, typecheck, build, migration checks, security fixtures, and the root `make` quality gates.

Required security fixtures include malicious ZIP/DOCX entries, oversized compression ratios, symlink/absolute-path entries, malformed PDFs, traversal attempts, provider private-IP/redirect/DNS-rebinding attempts, and log assertions that no key or raw secret appears.

The PostgreSQL integration job creates a temporary Compose env file from `.env.example` with `mktemp` (never overwriting or deleting a user `.env`), disables implicit `.env` and host-variable overrides, and starts the integration profile with an explicit environment whitelist. It calls `scripts/wait-for-services.sh` with the same isolated environment, creates a per-run database, exports the generated `DATABASE_URL`, runs migrations and `pytest -m integration -q`, reports cleanup failures, and preserves the original exit code while dropping the database and Compose resources. The helper writes `DATABASE_URL`, `TEST_DATABASE_NAME`, and `TEST_DATABASE_HOST` to a private temporary env file; it exits cleanly when that file or target database is absent. Unit tests may use SQLite only for pure service tests; they cannot stand in for PostgreSQL constraint behavior.

The Playwright job independently runs setup-python, installs/configures uv, runs `uv sync --directory apps/api --locked`, installs Node/pnpm dependencies and Playwright browsers, and then executes all runtime work in one `run: |` block: it sets `RUNTIME_DIR="$RUNNER_TEMP/rag-eval-e2e"`, creates the temporary Compose env file from `.env.example` inside that fixed directory, starts Compose with `docker compose --env-file "$COMPOSE_ENV_FILE" --profile e2e up -d postgres redis`, waits with `scripts/wait-for-services.sh --compose-env-file "$COMPOSE_ENV_FILE"`, creates `.ci-e2e.env` with `scripts/ci/create-test-database.sh .ci-e2e.env "$COMPOSE_ENV_FILE"`, sources both env files, exports `APP_ENV=development DEV_ACTOR_ID=<fixed test UUID> DATABASE_URL=... PLAYWRIGHT_OUTPUT_DIR="$RUNTIME_DIR/playwright"`, runs migrations, executes the root-relative `uv run --project apps/api python scripts/seed-dev-data.py`, starts API and worker with `>"$RUNTIME_DIR/api.log" 2>&1` and `>"$RUNTIME_DIR/worker.log" 2>&1`, and waits for `/health/ready`, the worker ready file, and live processes. `apps/web/playwright.config.ts` sets `outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR ?? "test-results"` and alone starts/owns Web, so CI never starts a second Web process. The run invokes `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 pnpm --dir apps/web exec playwright test`. The worker readiness contract is: connect to PostgreSQL/Redis, pass a job poll, write the ready file, and remove it on shutdown. The same run block defines an idempotent cleanup function: if `.ci-e2e.env` is absent, `scripts/ci/drop-test-database.sh` exits 0; the trap saves `status=$?` before `set +e`, stops API/worker, conditionally drops the per-run database, stops Compose, and removes only temporary env files, then exits with the saved status. A later workflow step with `if: failure()` uploads `$RUNNER_TEMP/rag-eval-e2e/api.log`, `worker.log`, and `playwright/` before the runtime directory is removed; it does not depend on a shell variable from the prior step. The job uses deterministic parser/provider fakes; production authentication and real provider credentials are never used in CI.

The implementation must add `scripts/ci/create-test-database.sh`, `scripts/ci/drop-test-database.sh`, and `make test-integration`, and use `uv lock --directory apps/api --check` (not a root-level `uv lock --check`) wherever lock validation is documented.

## Acceptance criteria

- A user can upload each supported format and see an honest queued/processing/success/failure state.
- Unsupported, oversized, malformed, duplicate, and cancelled inputs have deterministic, documented errors.
- Parsed chunks retain source document version and page/paragraph location.
- A failed parse can be retried without mutating the failed historical attempt.
- Worker crash/lease expiry requeues a job safely and duplicate wake-ups do not duplicate chunks or candidate items.
- Candidate generation is opt-in, schema-validated, traceable to document version/chunks/config, and never treats provider output as published truth.
- A fake provider success test proves candidate dataset/items, evidence links, document-version/chunk hashes, automatic checks, and configuration provenance are persisted exactly once under duplicate wake-ups.
- Viewer/editor/admin permissions match the existing matrix; all mutations are audited.
- No path traversal, accidental overwrite, secret leakage, unbounded wait, parser resource escape, SSRF to private networks, or silent failure is present.
- Multi-file upload reports each file independently; referenced source versions remain recoverable.
- API contract generation remains diff-clean, CI remains reproducible, and all quality gates pass.

## Follow-up sequence

After this plan passes review, create the next plan for review queue operations, Gold Dataset publishing, and dataset version comparison. Adapter execution remains a separate plan and must consume the published dataset contract rather than reaching into ingestion internals.
