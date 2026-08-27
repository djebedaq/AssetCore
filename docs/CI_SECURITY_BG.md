# CI, зависимости и PostgreSQL конкурентност

PR #31 запазва четирите jobs: `frontend`, `backend`, `postgres`, `docker`.
Няма автоматично merge-ване, промяна на repository protection или бизнес данни.

## Python quality gate

```sh
python -m pip install -r backend/requirements.txt -r backend/requirements-ci.txt
python -m pip check
python -m compileall -q backend/app backend/alembic backend/scripts scripts tests
python -m ruff check backend/app backend/alembic backend/scripts scripts tests
```

`pyproject.toml` включва целия стандартен Ruff correctness набор `E4,E7,E9,F`
плюс `I` (imports), без CI override `--select E9`. Само съществуващият seed и
изрично изброени публикувани миграции 0007–0016 имат тесен `I001` ignore.
Миграциите не се редактират; бъдещи revisions не получават този ignore.
Двата bootstrap импорта в integrity CLI имат локален `E402` ignore, защото
следват необходимото добавяне на backend към `sys.path`.

`ruff format --check` е отложен: уеднаквяването на многобройните дълги редове в
съществуващия код би изисквало несвързан масов formatting diff. Това не отслабва
настоящия correctness/import gate. Новите нарушения спират CI.

## Audit политика

```sh
python scripts/audit_dependencies.py python --output security-reports/python-audit.json
python scripts/audit_dependencies.py frontend --output security-reports/frontend-audit.json
```

Python използва фиксиран `pip-audit` върху **реално инсталираните**, включително
транзитивни, зависимости (`--local --strict`). Frontend използва `pnpm audit`
след `pnpm install --frozen-lockfile`. Няма `--fix`, автоматично обновяване или
редактиране на lockfile по време на audit. GitHub/OSV aliases се дедуплицират.
Python severity идва от публичния OSV запис; frontend severity — от npm audit.

- HIGH, CRITICAL и UNKNOWN/неразпозната severity блокират CI.
- LOW/MODERATE остават в JSON отчета и се разглеждат при dependency review.
- Липсващ report, непроверен пакет, невалиден JSON, registry/OSV network failure
  или timeout са **неуспех**, не „0 уязвимости“. Retry се прави чрез повторен CI run.
- Advisory feeds са актуални онлайн данни. Фиксирани са инструментите, входните
  manifests и правилата, но резултатът може да се промени при нов advisory.
- Липсата на patch не дава автоматично изключение. При непоправим HIGH/CRITICAL
  maintainer документира риска и mitigation в review и добавя **точно**
  `ecosystem`, `package`, `version`, `advisory`, `reason`, `tracking_url`, `expires`
  в `security/dependency-audit-exceptions.json`. Изключението е за конкретната
  версия, с краен срок (ISO дата, expiry денят вече е невалиден), без wildcards.
  Изтекло/невалидно изключение спира CI. Текущият списък е празен.
- Суров stderr от auditor не се публикува: може да съдържа private index URL.
  Архивира се само нормализирана package/advisory информация и безопасен error code.

Security обновяванията в този PR адресират установените advisories:
Starlette 1.3.1 ([Range DoS](https://github.com/advisories/GHSA-82w8-qh3p-5jfq)),
съвместимата FastAPI 0.135.1, cryptography 50.0.0
([advisory](https://github.com/advisories/GHSA-g6cj-pr64-35w5)), pypdf 6.15.0
([advisory](https://github.com/advisories/GHSA-g867-7843-wf8q)), js-yaml 4.3.1
([advisory](https://github.com/advisories/GHSA-5p4m-2wfm-xmqj)) и nanoid 3.3.18
([advisory](https://github.com/advisories/GHSA-2v37-7h3g-55p8)). FastAPI 0.141.1
бе отхвърлена при проверката за съвместимост: router промяната нарушава текущия
authorization inventory. Validator-ът не е отслабен. Новият CI manifest фиксира
audit инструментите и pip; runtime образът не инсталира тези CI зависимости.

Корекцията на PR #31 обновява pypdf от 6.14.2 до 6.15.0 за двата runtime
MODERATE advisories [GHSA-fp3f-mc75-235c](https://github.com/advisories/GHSA-fp3f-mc75-235c)
и [GHSA-fwg2-594c-jp42](https://github.com/advisories/GHSA-fwg2-594c-jp42).
Test-only pytest е обновен от 8.3.4 до 9.0.3 за
[GHSA-6w46-j5rx-g56g](https://github.com/advisories/GHSA-6w46-j5rx-g56g).
Съвместимостта се проверява чрез целия backend suite, document/PDF/hash
регресиите и PostgreSQL job; pytest-cov остава 6.0.0. Не се добавят audit
изключения и severity политиката не се променя. Конкретните audit резултати
се архивират за exact CI commit, а не се приемат за вечна гаранция.

## Автоматизирани update PR-и и Actions

Dependabot проверява `/backend` (pip), `/frontend` (npm/pnpm) и GitHub Actions
всеки понеделник. Лимити: 3/3/2 отворени update PR-а. Само близки test tools,
React и ESLint minor/patch версии са групирани; major versions остават отделни.
Всеки PR изисква човешки review и merge; няма auto-merge конфигурация.

Всички Actions са фиксирани към проверени release commit SHA, с четим коментар:
checkout v4.3.1, setup-node v4.4.0, setup-python v5.6.0, upload-artifact v4.6.2.
Workflow token има само `contents: read`; checkout не запазва credentials.
Има job timeouts и pip cache, обвързан с manifests. Не са добавени външни
security Actions. Съществуващите Docker runtime проверки са запазени.

## Задължителни security/release проверки

CI изрично изпълнява migration history, authorization inventory, production
configuration regression tests, catalog source validator, EN/BG catalog
translation validator, full backend и frontend suites и release verifier.
BG/EN/RU UI key parity остава покрита от съществуващите tests.

```sh
python backend/scripts/validate_migration_history.py --require-all-protected
python backend/scripts/validate_authorization_inventory.py
PYTHONPATH=backend python backend/scripts/catalog_v2_validation.py
PYTHONPATH=backend python backend/scripts/build_catalog_translations.py --check
python -m pytest -q tests/test_runtime_deployment_hardening.py
python -m pytest -q -m "not postgres" --durations=10
python scripts/verify_release.py --output release-verification
```

PowerShell: задайте `$env:PYTHONPATH='backend'` преди catalog и translation командите.
Inventory и CycloneDX 1.6 артефактите са описани в `SOFTWARE_BOM.md`; те не са
сертификация и не включват OS/container packages.

### Постоянна защита на migration release кандидата

Обикновеният `validate_migration_history()` и CLI без flag остават диагностични:
нов unprotected revision се отчита в `new_unprotected_migrations`, но не прави
непроменената историческа част невалидна. Това е допустимо по време на разработка.

CI и PowerShell release orchestration задължително използват
`--require-all-protected`; `scripts/verify_release.py` използва същия строг
`validate_migration_release()`. Missing, mismatched **или** unprotected revision
дава `valid: false` и non-zero exit. `history_valid` отделно показва историческата
цялост. Release verifier спира преди мигриране на QA база или генериране на QA
документи при такъв проблем. Текущата база е 21 protected / 0 unprotected.

Постоянен lifecycle: създайте/редактирайте новата миграция → завършете реализацията
и тестовете → изчислете normalized-LF SHA-256 чрез `normalized_sha256()` → добавете
новия entry в `backend/alembic/migration_history_manifest.json` **в същия PR** →
strict CI трябва да премине → човешки review и merge. Следващ PR не е необходим
само за защита на предходната миграция. Публикуваните файлове и техните hashes
не се редактират; промени на схема след release се правят с нов revision.

Регресиите изпълняват реалния CLI срещу временни файлове: normal приема бъдеща
миграция, strict отказва, exact normalized-LF hash в временния manifest отключва
strict проверката. Отделно се проверяват missing/mismatched и non-zero exit на
самия release entrypoint, без редакция на repository baseline.

## Истински PostgreSQL конкурентни транзакции

`tests/postgres/test_concurrency.py` работи единствено с PostgreSQL база с точно
име `assetcore_test_concurrency`. URL се подава чрез
`ASSETCORE_POSTGRES_CONCURRENCY_URL`; никога не се отпечатва. Всеки тест създава
отделна случайна schema, изпълнява Alembic до head и зарежда проверения seed.
QA записи се създават само там. Накрая се премахва **само тази schema**, не базата.

Координатор държи `FOR UPDATE` lock на canonical реда. Двата worker-а имат
отделни sessions, транзакции и `pg_backend_pid()`. Barrier ги стартира заедно;
тестът проверява чрез `pg_stat_activity` и `pg_blocking_pids`, че **и двата**
реално чакат lock, преди да освободи координатора. Няма monkeypatch на locking,
document generation или canonical domain operations; това не са SQLite HTTP threads.
Barrier: 12 s; наблюдение: 10 s; DB lock timeout: 15 s; statement: 45 s;
future result: 50 s. При преждевременно приключил worker тестът се проваля.

Пет сценария проверяват точно един успех и един 409, финално DB състояние,
audit counts и липса на частични/осиротели записи:

1. Двойно издаване: един active transfer/batch, индивидуални DOCX/PDF и текущият
   batch signing document. Машината остава непроменена до подписване — съществуващият workflow.
2. Два open repairs: един ремонт, едно repair събитие и едно machine събитие.
3. APPROVED срещу REJECTED: един canonical decision и един approval/audit запис.
4. Две генерации на parts protocol: един OfficialDocument/version, два реални
   файла; canonical номерът, content hashes и snapshot не се променят при повторение.
5. Два emergency starts: един активен session, непроменена ownership/role,
   success и rejection audit без plaintext парола.

```sh
ASSETCORE_REQUIRE_POSTGRES_TESTS=true python -m pytest -q tests/postgres --durations=10
python scripts/postgres_smoke_test.py
```

Локално без QA URL PostgreSQL тестовете са изрично skipped. В PostgreSQL CI job
`ASSETCORE_REQUIRE_POSTGRES_TESTS=true` превръща липсващия URL в failure.
Изолираният migration/advisory-lock и encrypted backup/restore smoke остава
задължителен и използва други две QA бази. Не изпълнявайте тестовете върху production.
