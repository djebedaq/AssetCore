# OWNER-DATA-01 — проверка и доставка

PR: [#87 — OWNER-DATA-01: Add owner-only permanent data deletion](https://github.com/djebedaq/AssetCore/pull/87).
База: `61446a5c95c290d26711c3843ccfad4e8517e7a7` (origin/main при старта).
Клон: `assetcore-owner-data01-permanent-deletion`. Кодът и тестовете са в
`9cc505a151b9be9e5a053cfff213c50ec3923601`; следващата промяна е само този отчет.
Окончателният HEAD е в PR и финалния отчет, за да не се записва самореферентен
commit SHA в съдържанието на неговия собствен commit.
Работата е само в development checkout. Production не е достъпван, променян,
мигриран, рестартиран или deploy-ван. Предварително наличните непроверени от Git
release-verification артефакти са запазени и не са част от промяната.

## Изпълнени локални проверки

Python командите използват `.venv/Scripts/python.exe`; `pnpm` се изпълнява във
frontend. Резултатите разграничават локалните проверки от отделната CI среда.

| Команда | Резултат |
|---|---|
| `python -m pytest -q tests/test_category_administration.py tests/test_owner_transfer_round_trip.py tests/test_i18n_roles_seed.py` | 22 passed |
| `python -m pytest -q tests/test_owner_data_deletion.py --durations=5` | 46 passed, 3 warnings; първоначален пакет преди допълнителните случаи |
| `PYTHONPATH=.tmp;backend python -m pytest -q tests/test_owner_data_deletion.py -n 2 -p asset01d_xdist_bootstrap --durations=5` | **53 passed**, 10 warnings, 717.46 s; локалният временен plugin възпроизвежда bearer bootstrap на conftest за xdist workers |
| `python -m pytest -q tests/test_authorization_web_security.py` | **13 passed**, 3 warnings, 120.71 s след обновяване на очакваните route counts |
| `PYTHONPATH=.tmp;backend python -m pytest -q -m "not postgres" -n 4 -p asset01d_xdist_bootstrap --durations=10` | Прекратен след остарялото очакване за route counts, заредено преди корекцията; не е пълен PASS. Финалният пълен пакет се изпълнява от CI без xdist/plugin |
| `python -m pytest -q tests/postgres` | 39 skipped: няма конфигурирана отделна PostgreSQL QA база; не е PostgreSQL PASS |
| `pnpm exec vitest run src/features/administration/OwnerDeleteButton.test.tsx` | 16 passed |
| `pnpm test` | 518 passed, 1 failed: съществуващият lazy catalog handoff тест изтече при паралелно натоварване |
| `pnpm exec vitest run --maxWorkers=2` | **519 passed**, 46 files, 79.47 s; повторен пълен пакет |
| `pnpm typecheck`, `pnpm lint`, `pnpm build` | Изпълнени успешно след корекцията на типовете/unused arguments в новите тестове |
| `python -m pip check` | No broken requirements found |
| `python -m compileall -q backend/app backend/alembic backend/scripts scripts tests` | exit 0 |
| `python -m ruff check backend/app backend/alembic backend/scripts scripts tests` | PASS, включително повторение след последните тестови добавки |
| `python backend/scripts/validate_migration_history.py --require-all-protected` | valid, 24 protected, без липси/промени/нови миграции |
| `python -m alembic -c backend/alembic.ini heads` | един head `20260924_0024` |
| `python backend/scripts/validate_authorization_inventory.py` | valid=true, 180 routes, 83 mutations |
| `PYTHONPATH=backend python backend/scripts/catalog_v2_validation.py` | valid=true, 611 records, 9 sources |
| `PYTHONPATH=backend python backend/scripts/build_catalog_translations.py --check` | exit 0 |
| `python scripts/verify_release.py --output .tmp/owner-data-release` | 26/26 проверки passed |
| `python backend/scripts/document_qa.py .tmp/owner-data-document-qa` | 13/13 release checks; controlled source hashes unchanged |
| AST сравнение на MACHINES/LOCATIONS спрямо базата | точна идентичност; 19 машини |
| `git diff --check` | PASS |
| Docker build/smoke/upgrade/backup/restore | Не е изпълнено локално: daemon не е стартиран; отделният CI job е успешен |

Логовете и генерираните QA файлове са временни development артефакти, не
продукционни записи. Реалните PostgreSQL overlap тестове използват съществуващия
disposable migrated schema fixture и CI job-а с изрично задължителна QA база.
## CI доказателства

[Build check #246](https://github.com/djebedaq/AssetCore/actions/runs/36313726165)
проверява implementation commit `9cc505a151b9be9e5a053cfff213c50ec3923601`:

* `postgres`: **39 passed**, 41 warnings, 215.77 s; четирите нови реални overlap
  случая са включени. Проверени са и PostgreSQL миграциите и криптираният
  backup/restore round trip.
* `frontend`: **519 passed**, 46 files; dependency security, typecheck, lint и
  production build са успешни.
* `docker`: успешни production image build, Compose init/restart/verified-backup
  upgrade, PostgreSQL client contract, encrypted round trip/PG17 rejection,
  non-root runtime, backup, read-only LibreOffice, official visual appendix и
  liveness/readiness smoke.
* `backend`: пълната команда е
  `python -m pytest -q -m "not postgres" --durations=10`; след нея CI изпълнява
  `python scripts/verify_release.py --output release-verification`. Точният
  окончателен брой е в job log и финалния PR отчет. CI включва pip check,
  dependency security, compileall, Ruff, migration history, authorization,
  catalog/translation и production configuration gates.

[PR checks](https://github.com/djebedaq/AssetCore/pull/87/checks) са източникът
за резултата върху най-новия HEAD, включително последващия commit само с отчет.
Draft се премахва само след преглед на успешните проверки. Не е правен
merge или deployment.

## Променени файлове

Общо 20 файла спрямо базата:

* Backend: `authorization_inventory.py`, `catalog/importer.py`,
  `governance/owner_data_deletion.py`, `governance/owner_data_routes.py`,
  `hardening_api.py`, `seed.py` (в `backend/app`).
* Frontend: `AdministrationPanel.tsx`, `CategoryAdministration.tsx`,
  `OwnerDeleteButton.tsx`, `OwnerDeleteButton.test.tsx`, `OwnerSigningData.tsx`,
  `UserAdministration.tsx` (в `frontend/src/features/administration`),
  `features/machines/MachineModal.tsx`, `i18n.tsx`, `styles.css`.
* Tests: `tests/test_owner_data_deletion.py`,
  `tests/postgres/test_owner_data_deletion_postgres.py`,
  `tests/test_authorization_web_security.py`.
* Docs: този отчет и `docs/OWNER_DATA_01_PERMANENT_DELETION_BG.md`.

Финалният diff е прегледан специално за seed/source/binary промени:
MACHINES/LOCATIONS са AST-идентични с базата, SOURCE_REGISTER, backend/resources,
DOCX/PDF и database файлове нямат промени. Няма schema/миграционна промяна.

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
21. ASSET-01 и останалите системни регресии — целевите 22 passed; целият backend пакет се проверява от CI, frontend е 519 passed, PostgreSQL е 39 passed, backup/update/smoke проверките са зелени.
22. Production — недокоснат; няма merge/deploy.

Подробният инвентар, per-resource правила, договори, audit и seed/concurrency
решения са в [OWNER_DATA_01_PERMANENT_DELETION_BG.md](OWNER_DATA_01_PERMANENT_DELETION_BG.md).
