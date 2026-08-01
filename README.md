# AssetCore — industrial asset management

FastAPI + React/TypeScript PWA for industrial assets, with a verified HPWJ register, guarded bulk transfers, return workflows, protocols, repairs, QR codes, technical documents, immutable audit history, and Bulgarian/English/Russian UI localization.

The final access model has exactly four roles: `administrator`, `director`, `mechanic`, and read-only `observer`. A single protected system owner is selected by `ASSETCORE_OWNER_EMAIL`; centralized backend permissions protect every operation. The user-administration workflow supports scoped account creation/editing, activation/deactivation, temporary-password resets, forced password changes, session invalidation, and audit records without password material.

For an existing deployment, configure `ASSETCORE_OWNER_EMAIL` before applying Alembic revision `20260801_0004_final_user_roles`. Legacy roles are migrated without deleting user-linked operational history.

See [README_BG.md](README_BG.md) for setup, operation and deployment instructions.
