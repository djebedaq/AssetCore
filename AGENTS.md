# Stable project rules for Codex work

These rules apply to the complete AssetCore repository.

- Never invent industrial assets, serial numbers, brands, locations, users, repairs, parts, documents, protocols or historical business records.
- Preserve the verified 19-machine HPWJ inventory and treat `docs/SOURCE_REGISTER_BG.md` plus the verified seed data as the source of truth.
- Do not add fake demonstration records to a production or committed database.
- Keep all user-facing interface text in Bulgarian and preserve responsive phone/desktop usability.
- Maintain PostgreSQL production compatibility and SQLite local/test compatibility. Use Alembic for schema changes.
- Enforce important business rules server-side. Transfer issue/return changes must be atomic and race-safe; an active transfer relationship is authoritative.
- Never expose, print or commit passwords, tokens, API keys, Render secrets, `.env` values or internal filesystem paths.
- Preserve QR behavior, repair history, audit history, transfer history, generated protocols and the technical-document library.
- Do not rewrite or delete existing audit or document history during normal feature work.
- Run tests and quality checks that the repository supports. Report exact commands and results honestly; never state that an unexecuted check passed.
- Review the final diff specifically for unintended changes to seed data, source registers, binary documents and other verified business material.
