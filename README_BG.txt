AssetCore v12 — pnpm test hotfix

Замени папката frontend от този hotfix върху папката на repository-то.
Променят се само:
- frontend/src/BulkTransfers.tsx
- frontend/src/IndustrialPlatform.test.tsx
- frontend/src/i18n.test.tsx

Поправки:
1. Достъпно и еднозначно label свързване за причината при анулиране.
2. Тестът на визуалния каталог използва актуалния machine-filtered API endpoint и пълен verified part fixture.
3. i18n тестът очаква задължителния бутон „Издай“, а не стария текст „Групово издаване“.
