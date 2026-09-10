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
| `markdown-it-py` | 3.0.0 | MIT | CommonMark normalization validation; lock: `mdurl` |
| `lxml` | 6.1.3 | BSD-3-Clause | Transitive `python-docx` XML implementation |
| `mdurl` | 0.1.2 | MIT | Transitive URL utility used by `markdown-it-py` |

The transitive versions above are taken from the committed
`apps/api/uv.lock` (`python-docx -> lxml`, `markdown-it-py -> mdurl`). License
sources are the package metadata and upstream license files: [lxml PyPI]
(https://pypi.org/project/lxml/6.1.3/), [lxml LICENSES.txt]
(https://github.com/lxml/lxml/blob/master/LICENSES.txt), [mdurl PyPI]
(https://pypi.org/project/mdurl/0.1.2/), and [mdurl LICENSE]
(https://github.com/executablebooks/mdurl/blob/master/LICENSE).

These dependencies are used only behind the documented parser/storage
boundaries. No dependency grants permission to redistribute user documents or
provider responses. Contributions must update this inventory and verify the
upstream license when changing versions.
