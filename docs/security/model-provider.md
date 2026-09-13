# Model Provider Security Boundary

Model providers are opt-in. A provider endpoint must be explicitly present in
the host and port allowlists; production endpoints must use HTTPS. The
transport resolves the hostname before connecting, rejects private, loopback,
and link-local addresses, disables redirects, applies bounded timeouts, and
returns only redacted error messages.

API keys are injected through `PROVIDER_API_KEY` or a future secret manager.
They are never included in generation snapshots, ordinary logs, API responses,
or exception text. Connection tests use synthetic input. A deployment must
review which document chunks and candidate prompts are sent to the configured
provider before enabling generation.

The OpenAI-compatible implementation accepts only a validated JSON response;
malformed or incomplete output is rejected and cannot create candidate data.
If no provider is configured, the public API reports
`provider_not_configured` and never silently selects the test provider.
