# Dependency License Inventory

This file records the direct runtime dependencies added for document ingestion.
Versions are pinned in `apps/api/pyproject.toml` and resolved in
`apps/api/uv.lock`. Before a release, regenerate the full transitive inventory
from the lock file and review license and security changes.

| Package | Version | License | Purpose |
| --- | --- | --- | --- |
| `httpx` | 0.28.1 | BSD-3-Clause | bounded future provider HTTP transport |
| `python-multipart` | 0.0.20 | Apache-2.0 | future multipart upload parsing |
| `pypdf` | 5.4.0 | BSD-3-Clause | bounded PDF parser |
| `python-docx` | 1.1.2 | MIT | bounded DOCX parser after ZIP validation |
| `markdown-it-py` | 3.0.0 | MIT | CommonMark normalization validation |

These dependencies are used only behind the documented parser/storage
boundaries. No dependency grants permission to redistribute user documents or
provider responses. Contributions must update this inventory and verify the
upstream license when changing versions.
