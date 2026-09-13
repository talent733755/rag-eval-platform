# Adapter v1

`adapter-v1` is the provider-neutral contract used by experiments to call a
project's RAG system. HTTP and Python adapters must produce the same validated
`AdapterResponse`; neither adapter may access an API database session.

The request contains a bounded question, at most 20 context entries, a stable
request ID, and a per-item timeout. A response contains a non-empty answer,
optional citations tied to source/chunk IDs, usage and latency, and an optional
trace envelope. Unknown fields are rejected so contract drift is visible.

Adapter configuration and credentials are separate from this payload. Keys are
never placed in request metadata, trace stages, audit events, or normal logs.
Implementations must enforce HTTPS/allowlists, bounded response bodies,
timeouts, cancellation and redacted errors before making network calls.

The built-in HTTP implementation posts JSON to `/invoke`, refuses redirects,
limits response bodies to 2 MiB, and classifies 429/5xx/timeout failures as
retryable without exposing upstream response bodies. A bearer token is supplied
only through configuration and is never part of the contract snapshot.

The capability version is fixed to `adapter-v1`. Compatible additions require a
new optional field and a regenerated client; changes to citation meaning,
timeout semantics or trace structure require a new capability version and an
explicit migration.

## Configuration API

Project members can read adapter configuration through `GET /api/projects/{project_id}/adapters`
and `GET /api/projects/{project_id}/adapters/{adapter_id}`. Editors can create and partially
update configurations with `POST` and `PATCH`; administrators can delete them with `DELETE`.
Responses contain only the credential reference and, for Python adapters, the exact trusted
`entrypoint_ref`; they never contain credential values.

`POST /api/projects/{project_id}/adapters/{adapter_id}/test` performs one bounded synthetic
request (`question: "连接测试"`, metadata purpose `connection_test`) against an HTTP adapter.
It updates `last_test_status` to `succeeded` or `failed`. Missing credential references,
disallowed network destinations, invalid responses, timeouts and upstream failures return a
stable error code and never include the upstream body. For Python adapters, `entrypoint_ref` must
match exactly one installed package entry point in the `rag_eval_adapter` group. The server loads
that entry point in the process-isolated Python SDK adapter; it never evaluates source strings or
user-submitted code. Missing or ambiguous entries return `adapter_entrypoint_unavailable`.
