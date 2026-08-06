ASSETCORE v12.1 — LIVE BUGFIX

1. В GitHub Desktop избери branch main и натисни Fetch origin / Pull origin.
2. Създай нов branch: assetcore-v12-1-live-bugfix.
3. Repository -> Show in Explorer.
4. Копирай съдържанието на този hotfix директно в корена на repository-то.
5. Потвърди Replace the files in the destination.
6. Commit: Fix live transfer repair and catalog regressions
7. Push origin и отвори Pull Request към main.
8. Изчакай всички GitHub проверки да станат зелени.
9. Merge и в Render: Manual Deploy -> Clear build cache & deploy.

Поправя:
- приемане на машини с checklist без клиентски label;
- смесени части в ремонтната карта;
- явен избор и маркиране на позиция в каталога;
- legacy несъответствие между ремонтен и машинен статус;
- запис на допълнителни участници;
- idempotent migration 20260805_0015.
