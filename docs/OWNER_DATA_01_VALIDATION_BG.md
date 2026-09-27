# OWNER-DATA-01 — проверка и доставка

База: `61446a5c95c290d26711c3843ccfad4e8517e7a7` (origin/main при старта).
Клон: `assetcore-owner-data01-permanent-deletion`.
Работата е само в development checkout. Production не е достъпван, променян,
мигриран, рестартиран или deploy-ван. Предварително наличните непроверени от Git
release-verification артефакти са запазени и не са част от промяната.

## Локални проверки към първоначалното публикуване

Python командите използват `.venv/Scripts/python.exe`; `pnpm` се изпълнява във
frontend. Резултатите по-долу разграничават изпълнени от чакащи проверки.

| Команда | Резултат |
|---|---|
| `python -m pytest -q tests/test_category_administration.py tests/test_owner_transfer_round_trip.py tests/test_i18n_roles_seed.py` | 22 passed |
| `python -m pytest -q tests/test_owner_data_deletion.py --durations=5` | 46 passed, 3 warnings; преди допълнителните случаи за signed/PARTS-DOC/bootstrap |
| `python -m pytest -q tests/test_owner_data_deletion.py -n 2 -p asset01d_xdist_bootstrap --durations=5` | Изпълнява се върху разширения финален пакет; локалният plugin в .tmp възпроизвежда bearer bootstrap на conftest за xdist workers |
| `python -m pytest -q -m "not postgres" -n 4 -p asset01d_xdist_bootstrap --durations=10` | Изпълнява се; финалните резултати ще бъдат добавени |
| `python -m pytest -q tests/postgres` | 39 skipped: няма конфигурирана отделна PostgreSQL QA база; не е PostgreSQL PASS |
| `pnpm exec vitest run src/features/administration/OwnerDeleteButton.test.tsx` | 16 passed |
| `pnpm test` | 518 passed, 1 failed: съществуващият lazy catalog handoff тест изтече при паралелно натоварване; повторната пълна проверка с два workers се изпълнява |
| `pnpm typecheck`, `pnpm lint`, `pnpm build` | Изпълнени успешно след корекцията на типовете/unused arguments в новите тестове |
| `python -m pip check` | No broken requirements found |
| `python -m compileall -q backend/app backend/alembic backend/scripts scripts tests` | exit 0 |
| `python -m ruff check backend/app backend/alembic backend/scripts scripts tests` | PASS; ще се повтори след последните тестови добавки |
| `python backend/scripts/validate_migration_history.py --require-all-protected` | valid, 24 protected, без липси/промени/нови миграции |
| `python -m alembic -c backend/alembic.ini heads` | един head `20260924_0024` |
| `python backend/scripts/validate_authorization_inventory.py` | valid=true, 180 routes, 83 mutations |
| `PYTHONPATH=backend python backend/scripts/catalog_v2_validation.py` | valid=true, 611 records, 9 sources |
| `PYTHONPATH=backend python backend/scripts/build_catalog_translations.py --check` | exit 0 |
| `python scripts/verify_release.py --output .tmp/owner-data-release` | 26/26 проверки passed |
| `python backend/scripts/document_qa.py .tmp/owner-data-document-qa` | 13/13 release checks; controlled source hashes unchanged |
| AST сравнение на MACHINES/LOCATIONS спрямо базата | точна идентичност; 19 машини |
| `git diff --check` | PASS |
| Docker build/smoke/upgrade/backup/restore | Не е изпълнено локално: daemon не е стартиран; чака GitHub CI |

Логовете и генерираните QA файлове са временни development артефакти, не
продукционни записи. Реалните PostgreSQL overlap тестове използват съществуващия
disposable migrated schema fixture и CI job-а с изрично задължителна QA база.
Първоначално PR се публикува като draft, за да се изпълнят PostgreSQL и Docker
проверките, докато локалният пълен пакет завършва. Не се заявява готовност преди
прегледа на резултатите.

## Преглед на изискванията

1. Физически DELETE на основния ред — реализиран и тестван.
2. Обикновен администратор няма достъп — изричен owner guard; четирите роли са тествани.
3. Текущият owner/себе си са защитени — preview blocker и 409 при execute.
4. Текуща парола — съществуващият verifier и sensitive throttling; отказът не изтрива.
5. Точна фраза — сървърно сравнение и UI условие; неточна фраза не изтрива.
6. Повторна проверка на зависимости — след writer/table/row locks; stale preview е тестван.
7. Документи/история не се каскадират — Core DELETE, FK анализ и explicit owned cleanup.
8. Нов unused user/не-owner administrator — физически DELETE и запазен одит.
9. Unused department/location — физически DELETE; текущи/исторически връзки блокират.
10. Unused category/field — физически DELETE; unused полета се почистват само изрично.
11. Нов погрешен актив — физически DELETE на реда и baseline owned данните.
12. Актив с история — блокиран; ремонти/предавания/заявки/документи не се изтриват.
13. Причини и броеве — стабилни кодове, преведени BG/EN/RU labels.
14. Изтрит seed ресурс остава липсващ — регресии с два seed run-а; bootstrap-only registry.
15. Нова инсталация получава проверения bootstrap — conftest и rollback/retry тест.
16. Одит за успешното изтриване — в същата транзакция и остава след DELETE.
17. Сесии на изтрит user — физически се премахват; bearer/browser проверки.
18. Инвентар на deactivation ресурсите — всички 14 is_active модела в архитектурния документ.
19. Workflow/security flags — изрично изключени; няма пета роля или RBAC delete permission.
20. 19 HPWJ при fresh bootstrap — потвърдено от seed регресиите и непроменените константи.
21. ASSET-01 и останалите системни регресии — целевите 22 passed; пълният пакет/CI още се изпълняват.
22. Production — недокоснат; няма merge/deploy.

Подробният инвентар, per-resource правила, договори, audit и seed/concurrency
решения са в [OWNER_DATA_01_PERMANENT_DELETION_BG.md](OWNER_DATA_01_PERMANENT_DELETION_BG.md).
