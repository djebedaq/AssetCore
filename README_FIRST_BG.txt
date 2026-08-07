AssetCore v12.3.1 — CI + PostgreSQL return fix

Този hotfix комбинира:
1) PostgreSQL поправката за bulk return row locking.
2) Поправка на backend CI теста, който отказва hardcoded кирилица в React компонентите.

Копирай директно в корена на repository-то и замени файловете.

Трябва да се променят:
- backend/app/transfer_service.py
- frontend/src/BulkTransfers.tsx
- frontend/src/i18n.tsx
- tests/test_bulk_transfers.py

Commit message:
Fix PostgreSQL return locking and CI localization
