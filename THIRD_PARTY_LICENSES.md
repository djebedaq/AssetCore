# Third-party licences

AssetCore's original code remains proprietary. Third-party components remain
under their upstream licences. This inventory was checked against the installed
Python package metadata and frontend package metadata on 2026-08-01; the lockfile
and the packages shipped in the final image remain authoritative.

| Package | Verified installed/version | Licence | Package source | Proprietary commercial use | Required action / known risk |
|---|---:|---|---|---|---|
| FastAPI | 0.115.6 | MIT | PyPI / github.com/fastapi/fastapi | Yes | Retain copyright and licence notice; review Starlette/Pydantic transitives. |
| Uvicorn | 0.34.0 | BSD-3-Clause | PyPI / uvicorn.org | Yes | Retain BSD notice and disclaimer. |
| SQLAlchemy | 2.0.36 | MIT | PyPI / sqlalchemy.org | Yes | Retain MIT notice. |
| Alembic | 1.14.0 | MIT | PyPI / alembic.sqlalchemy.org | Yes | Retain MIT notice. |
| psycopg / psycopg-binary | 3.2.3 | LGPL-3.0-only (package metadata) | PyPI / psycopg.org | Generally yes, subject to LGPL | Preserve licence/notices and relinking/replacement rights where applicable; binary distribution and bundled libpq/OpenSSL need release-specific legal review. |
| Pydantic | 2.10.4 | MIT | PyPI / github.com/pydantic/pydantic | Yes | Retain MIT notice; include pydantic-core transitive licence. |
| pydantic-settings | 2.7.0 | MIT | PyPI / github.com/pydantic/pydantic-settings | Yes | Retain MIT notice. |
| qrcode | 8.0 | BSD-style | PyPI / github.com/lincolnloop/python-qrcode | Yes | Retain upstream BSD notice. |
| ReportLab | 4.2.5 | BSD-style | PyPI / reportlab.com | Yes | Retain `license.txt`; bundled fonts may have separate terms. |
| python-docx | 1.1.2 | MIT | PyPI / github.com/python-openxml/python-docx | Yes | Retain MIT notice; include lxml transitive notices. |
| cryptography | 44.0.0 | Apache-2.0 OR BSD-3-Clause | PyPI / github.com/pyca/cryptography | Yes | Select/retain applicable notice; review OpenSSL/Rust transitive notices in distributed wheels. |
| pypdf | 5.1.0 | BSD-3-Clause | PyPI / github.com/py-pdf/pypdf | Yes | Retain BSD notice. |
| React | 19.2.8 | MIT | npm / github.com/facebook/react | Yes | Retain MIT notice. |
| React DOM | 19.2.8 | MIT | npm / github.com/facebook/react | Yes | Retain MIT notice. |
| lucide-react | 0.468.0 | ISC | npm / lucide.dev | Yes | Retain ISC notice; icon trademarks are not granted by the software licence. |
| Recharts | 2.15.4 | MIT | npm / github.com/recharts/recharts | Yes | Retain MIT notice; include D3/transitive notices. |
| Vite | 6.4.3 | MIT | npm / vite.dev | Yes | Build-only; retain notices for any runtime code bundled from dependencies. |
| TypeScript | 5.9.3 | Apache-2.0 | npm / github.com/microsoft/TypeScript | Yes | Build-only; retain Apache notice if redistributed. |
| Vitest | 3.2.7 | MIT | npm / github.com/vitest-dev/vitest | Yes | Development-only; normally not in production image. |
| ESLint | 9.39.5 | MIT | npm / eslint.org | Yes | Development-only; retain notice if redistributed. |
| jsdom | 26.1.0 | MIT | npm / github.com/jsdom/jsdom | Yes | Test-only; review transitive licences if packaged. |
| Testing Library React | 16.3.2 | MIT | npm / github.com/testing-library/react-testing-library | Yes | Test-only. |
| Testing Library user-event | 14.6.1 | MIT | npm / github.com/testing-library/user-event | Yes | Test-only. |
| pytest / pytest-cov | 8.3.4 / 6.0.0 | MIT | PyPI / pytest.org | Yes | Development-only. |
| Ruff | 0.8.4 | MIT | PyPI / docs.astral.sh/ruff | Yes | Development-only. |

## Release obligations

- Generate a complete transitive inventory from the final Python environment,
  `frontend/pnpm-lock.yaml`, and built container. The direct table above is not a
  substitute for transitive notices.
- Ship upstream licence texts/notices required by the exact artifacts. Do not
  remove existing third-party notices or claim ownership of external code,
  manuals, fonts or binaries.
- Confirm the LGPL obligations for the exact psycopg binary distribution and
  the licences of LibreOffice, Poppler, fonts, PostgreSQL client tools, libpq and
  OpenSSL used in the production image.
- Run a qualified legal review before commercial distribution. “Generally yes”
  is an engineering inventory statement, not legal advice.

Reference sources include the package metadata installed by pip/npm and the
upstream React MIT licence, TypeScript Apache-2.0 licence, pyca/cryptography dual
licence, and Psycopg LGPL declaration.
