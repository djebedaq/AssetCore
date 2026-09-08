# AssetCore software bill of materials

Generated from the direct dependency manifests for the 2026 production-hardening
release. Transitive frontend dependencies and integrity hashes are authoritative
in `frontend/pnpm-lock.yaml`; Python direct versions are authoritative in
`backend/requirements*.txt`.

## Runtime

- Python 3.12; FastAPI 0.135.1; Starlette 1.3.1; Uvicorn 0.34.0;
  SQLAlchemy 2.0.36; Alembic 1.14.0;
  psycopg 3.2.3; Pydantic 2.10.4; pydantic-settings 2.7.0; qrcode 8.0;
  ReportLab 4.2.5; python-docx 1.1.2; cryptography 50.0.0; pypdf 6.16.2;
  PyMuPDF 1.26.7.
- Node.js 22; installed React/React DOM 19.2.8; Lucide React 0.468.0;
  Recharts 2.15.4; Vite 6.4.3. Manifest ranges and exact lockfile resolutions
  must both be archived with the release.
- PostgreSQL 16 production; SQLite development/test; LibreOffice Writer and
  DejaVu fonts in the production container.

## Development and QA

- pytest 9.1.1; pytest-cov 6.0.0; Ruff 0.16.4 (existing direct manifest pins).
- CI inventory/audit tools: pip 26.2.1; pip-audit 2.10.1; PyYAML 6.0.3
  (`backend/requirements-ci.txt`). These are not production runtime requirements.
- Installed TypeScript 5.9.3; ESLint 9.39.5; Vitest 3.2.7; jsdom 26.1.0;
  Testing Library React 16.3.2 and user-event 14.6.1.
- PROD-01 qualification: ESLint's transitive `js-yaml` is locked to **4.3.2**
  to resolve the inherited HIGH [GHSA-2883-xcg3-v3hh](https://github.com/advisories/GHSA-2883-xcg3-v3hh).
  No application runtime dependency or audit severity policy is changed.

## Reproducibility

Run `scripts/verify_release.ps1` and archive the command report, lockfile hashes,
container digest, migration head and generated document QA manifest with the
release. Do not put secrets or private licence-signing keys in an SBOM.

Install the exact runtime and CI manifests before release verification:

```sh
python -m pip install -r backend/requirements.txt -r backend/requirements-ci.txt
python scripts/dependency_inventory.py --output release-verification
python scripts/verify_release.py --output release-verification
```

Both commands write `dependency-inventory.json` and standard CycloneDX 1.6
`sbom.cdx.json`. The inventory verifies direct Python pins and frontend
manifest/lockfile parity, records every installed Python distribution and all
resolved pnpm packages (including optional/platform packages), and preserves
their SHA-512 integrity hashes. Inputs have normalized-LF SHA-256 hashes. Sorted
output has no timestamps, local paths, credentials or private signing material.
Identical installed dependencies and manifests produce identical output. Python
transitive resolution remains platform/time dependent; the inventory records
the actual resolved environment, not a claim of a fully hash-locked Python build.

The backend CI artifact contains the inventory, CycloneDX file, audit report and
existing release QA. Frontend audit and PostgreSQL JUnit reports have separate
artifacts. OS packages and container layers are outside this SBOM's scope; no
formal compliance certification is claimed. See [CI policy](docs/CI_SECURITY_BG.md).
