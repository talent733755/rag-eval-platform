# Dependency License Inventory

This file records the direct runtime dependencies added for document ingestion.
Versions are pinned in `apps/api/pyproject.toml` and resolved in
`apps/api/uv.lock`. Before a release, regenerate the full transitive inventory
from the lock file and review license and security changes.

| Package | Version | License | Purpose |
| --- | --- | --- | --- |
| `httpx` | 0.28.1 | BSD-3-Clause | bounded future provider HTTP transport |
| `python-multipart` | 0.0.20 | Apache-2.0 | future multipart upload parsing |
| `pypdf` | 5.4.0 | BSD-3-Clause | future PDF parser |
| `python-docx` | 1.1.2 | MIT | future DOCX parser |
| `markdown-it-py` | 3.0.0 | MIT | future Markdown parser |

These dependencies are runtime prerequisites only; this phase does not invoke
their parser or provider functionality. No dependency grants permission to
redistribute user documents or provider responses. Contributions must update
this inventory and verify the upstream license when changing versions.
