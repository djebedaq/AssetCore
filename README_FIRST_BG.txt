ASSETCORE v12 — DIRECT TEST HOTFIX

ВАЖНО: Този ZIP няма външна обвиваща папка. След разархивиране ще видиш директно папка "frontend".

1. В GitHub Desktop избери branch: assetcore-v12-final.
2. Repository -> Show in Explorer.
3. Копирай папката "frontend" от този hotfix директно в корена на repository-то.
4. Избери Replace the files in the destination.
5. В GitHub Desktop трябва да се покажат ТОЧНО тези 3 променени файла:
   - frontend/src/BulkTransfers.tsx
   - frontend/src/IndustrialPlatform.test.tsx
   - frontend/src/i18n.test.tsx
6. Ако тези 3 файла не се показват, НЕ прави commit — копирано е на грешно място.
7. Commit message: Fix remaining frontend tests
8. Push origin.

Проверки в самите файлове:
- BulkTransfers.tsx съдържа htmlFor={`cancel-reason-${batch.batch_id}`} и textarea id.
- i18n.test.tsx очаква translate('bg', 'bulk.issue') да е 'Издай'.
- IndustrialPlatform.test.tsx mock-ва /api/catalog/parts?verified_only=true&machine_id= и verified part с assembly.
