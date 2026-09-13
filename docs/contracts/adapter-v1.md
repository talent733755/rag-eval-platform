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
