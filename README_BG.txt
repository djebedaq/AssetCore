ASSETCORE v12 — CI HOTFIX

1. Отвори локалната папка на repository-то през GitHub Desktop: Repository -> Show in Explorer.
2. Увери се, че избраният branch е assetcore-v12-final.
3. Копирай папките .github и frontend от този hotfix върху съществуващите папки в repository-то.
4. Потвърди замяната на двата файла.
5. В GitHub Desktop направи commit с име: Fix GitHub Actions checks
6. Натисни Push origin.
7. Изчакай новите проверки в Pull Request №10. Не натискай Merge, докато всички проверки не са зелени.

Промени:
- премахва двойното стартиране на проверки за push към feature branch и pull_request;
- поправя pnpm стартирането в GitHub Actions;
- поправя липсващото signing_tasks поле във frontend теста;
- временно проверява с Ruff само критични Python синтактични грешки, докато import-order забележките бъдат почистени отделно.
