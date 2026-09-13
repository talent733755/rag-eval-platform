# Dependency License Inventory

This file records the direct runtime dependencies used by the API and Web
applications, plus security-relevant transitive dependencies. Versions are
pinned in `apps/api/pyproject.toml`, `apps/web/package.json`, and resolved in
`apps/api/uv.lock`/`pnpm-lock.yaml`. Before a release, regenerate the full
transitive inventory and review license and security changes.

| Package | Version | License | Purpose |
| --- | --- | --- | --- |
| `httpx` | 0.28.1 | BSD-3-Clause | bounded future provider HTTP transport |
| `python-multipart` | 0.0.20 | Apache-2.0 | future multipart upload parsing |
| `pypdf` | 5.4.0 | BSD-3-Clause | bounded PDF parser |
| `python-docx` | 1.1.2 | MIT | bounded DOCX parser after ZIP validation |
| `markdown-it-py` | 3.0.0 | MIT | CommonMark normalization validation; lock: `mdurl` |
| `lxml` | 6.1.3 | BSD-3-Clause | Transitive `python-docx` XML implementation |
| `mdurl` | 0.1.2 | MIT | Transitive URL utility used by `markdown-it-py` |

## Web runtime and build boundary

| Package | Version | License | Purpose |
| --- | --- | --- | --- |
| `next` | 15.5.24 | MIT | Web application runtime and build |
| `react` | 19.1.0 | MIT | Web UI runtime |
| `react-dom` | 19.1.0 | MIT | React browser renderer |
| `postcss` | 8.5.28 | MIT | CSS transformation toolchain |
| `sharp` | 0.35.4 | Apache-2.0 | Next image processing dependency, pinned by root override |

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
upstream license when changing versions. The root `pnpm.overrides` keeps
`postcss` and `sharp` on security-fixed versions even when a framework requests
an older compatible range.
