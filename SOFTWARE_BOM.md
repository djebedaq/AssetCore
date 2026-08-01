# AssetCore software bill of materials

Generated from the direct dependency manifests for the 2026 production-hardening
release. Transitive frontend dependencies and integrity hashes are authoritative
in `frontend/pnpm-lock.yaml`; Python direct versions are authoritative in
`backend/requirements*.txt`.

## Runtime

- Python 3.12; FastAPI 0.115.6; Uvicorn 0.34.0; SQLAlchemy 2.0.36; Alembic 1.14.0;
  psycopg 3.2.3; Pydantic 2.10.4; pydantic-settings 2.7.0; qrcode 8.0;
  ReportLab 4.2.5; python-docx 1.1.2; cryptography 44.0.0; pypdf 5.1.0.
- Node.js 22; installed React/React DOM 19.2.8; Lucide React 0.468.0;
  Recharts 2.15.4; Vite 6.4.3. Manifest ranges and exact lockfile resolutions
  must both be archived with the release.
- PostgreSQL 16 production; SQLite development/test; LibreOffice Writer and
  DejaVu fonts in the production container.

## Development and QA

- pytest 8.3.4; pytest-cov 6.0.0; Ruff 0.8.4.
- Installed TypeScript 5.9.3; ESLint 9.39.5; Vitest 3.2.7; jsdom 26.1.0;
  Testing Library React 16.3.2 and user-event 14.6.1.

## Reproducibility

Run `scripts/verify_release.ps1` and archive the command report, lockfile hashes,
container digest, migration head and generated document QA manifest with the
release. Do not put secrets or private licence-signing keys in an SBOM.
