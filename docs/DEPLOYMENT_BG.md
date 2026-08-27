# Deployment и миграции

## Конфигурация

Задължителните продукционни environment variables са `DATABASE_URL`, `SECRET_KEY` (минимум 32 знака), `OWNER_FIRST_NAME`, `OWNER_MIDDLE_NAME`, `OWNER_LAST_NAME`, `OWNER_EMAIL`, `OWNER_JOB_TITLE`, стабилен `INSTALLATION_ID`, `LICENSE_PUBLIC_KEY` и отделен `SIGNATURE_ENCRYPTION_KEY` (минимум 32 знака). `OWNER_INITIAL_PASSWORD` е задължителна само при първия bootstrap върху база без потребители; след успешния вход и forced password change я премахнете от environment-а. Production изисква едновременно `DEPLOYMENT_ENVIRONMENT=production`, `PRODUCTION_MODE=true`, `LICENSE_ENFORCEMENT_ENABLED=true`, `MIGRATION_STRATEGY=external`, PostgreSQL и изрични HTTPS `PUBLIC_BASE_URL`/`FRONTEND_ORIGIN(S)`. Несъответствие отказва старт. Локалният Docker Compose изисква и `POSTGRES_PASSWORD`; паролата в `DATABASE_URL` трябва да е URL-encoded. Не поставяйте стойностите им в Git, issue, log или screenshot. `ASSETCORE_OWNER_EMAIL`/`ADMIN_*` остават само като legacy migration compatibility и не са новият bootstrap договор.

Generic Render URLs с `postgresql://` или legacy `postgres://` се нормализират към SQLAlchemy драйвера `postgresql+psycopg://`. SQLite URL остава непроменен.

Production и staging изискват изричен `FRONTEND_ORIGIN` или comma-separated
`FRONTEND_ORIGINS`. Стойността съдържа само `https://host[:port]`, без path,
query, credentials или wildcard. Тези среди не добавят localhost и отказват
старт без explicit origin. Development/test добавя Vite preview
`http://localhost:4173`. За Render задайте реалния HTTPS app origin; локалният
full-stack production-style Docker трябва да е зад HTTPS reverse proxy.

### Матрица на средите

| Среда | База | `PRODUCTION_MODE` | Миграции | Публични адреси | Лиценз |
|---|---|---:|---|---|---|
| development/test | SQLite или PostgreSQL | `false` | `startup` по подразбиране | localhost HTTP е допустим | по избор |
| staging | PostgreSQL | `false` | `startup` със advisory lock или отделна стъпка | изрично HTTPS | може да е изключен |
| production | PostgreSQL | `true` | само `external` | изрично HTTPS | задължително включен |

`render.yaml` е означен само за staging (`plan: free`, `DEPLOYMENT_ENVIRONMENT=staging`). Free Render web услугата няма платена pre-deploy стъпка, затова staging използва bounded `startup` migration под PostgreSQL advisory lock и една инстанция. Това не е production профил. За production използвайте платена услуга с отделна pre-deploy команда `python -m app.runtime prepare`, след което стартирайте неизменения web `CMD`.

### PostgreSQL pool и timeout настройки

| Променлива | Default | Значение |
|---|---:|---|
| `DB_POOL_PRE_PING` | `true` | проверява connection преди reuse |
| `DB_POOL_SIZE` | `5` | постоянни връзки на web процес |
| `DB_MAX_OVERFLOW` | `10` | временни връзки над pool-а |
| `DB_POOL_TIMEOUT_SECONDS` | `30` | bounded изчакване за connection |
| `DB_POOL_RECYCLE_SECONDS` | `1800` | периодично рециклиране; `0` изключва |
| `DB_CONNECT_TIMEOUT_SECONDS` | `10` | timeout при нова PostgreSQL връзка |
| `DB_STATEMENT_TIMEOUT_MS` | `0` | `0` не налага общ statement timeout |
| `MIGRATION_LOCK_TIMEOUT_SECONDS` | `60` | bounded изчакване за migration advisory lock |

`DB_STATEMENT_TIMEOUT_MS` умишлено е изключен по подразбиране, за да не прекъсва легитимни дълги document/backup операции. Променяйте го само след измерване и отделна оперативна проверка.

Browser session policy се управлява чрез `SESSION_MINUTES` (default 720) и
`SESSION_COOKIE_SAMESITE` (`lax` или `strict`). Staging/production автоматично
добавят `Secure`; localhost development го изключва, за да работи през HTTP.
`BEARER_COMPATIBILITY_ENABLED` трябва да остане `false` извън изрични локални
CLI/tests и settings отказва staging/production старт при `true`.

`TRUSTED_PROXY_IPS` е optional comma-separated IP/CIDR allowlist за
непосредствения reverse proxy. Само от такъв peer се приема `X-Forwarded-For`
за authentication throttling. Ако точните proxy мрежи не са потвърдени,
оставете стойността празна; никога не използвайте broad allowlist.

HSTS се изпраща само когато production request scope е HTTPS. Reverse proxy-то
трябва надеждно да предава HTTPS scheme към ASGI сървъра; не симулирайте HTTPS
чрез непроверен клиентски header. След deployment проверете CSP, HSTS, exact
CORS origin и отказа на непознат origin върху реалния staging URL.

## Миграция

Текущият `head` е `20260826_0021`. Той добавя `auth_sessions` и
`authentication_throttles` за durable hashed browser session, session-bound
CSRF и bounded authentication backoff. Миграцията е съвместима с PostgreSQL и
SQLite и отчита fresh-install поведението на historical revision 0001, без да
променя публикуваните миграции 0001–0020. Downgrade до 0020 премахва само тези
две таблици и прекратява всички browser сесии.

Предходният `20260826_0020` добавя unique owner key за `OfficialDocumentVersion`, PostgreSQL composite FK `official_documents(id, current_version_id) → official_document_versions(document_id, id)` и version-side trigger, както и SQLite trigger еквивалент. Преди guard-а миграцията отчита само броя на NULL, missing, wrong-owner, shared и orphan historical състояния. Тя не променя pointer, snapshot, binary document, signature или hash данни; PostgreSQL constraint се добавя `NOT VALID` и се валидира автоматично само когато existing current pointers са съвместими. Новите writes се пазят и при tolerated historical anomalies.

Предходният `20260818_0019` добавя source identity/metadata към `part_catalog`, active/source metadata към technical documents и repair kits, source metadata към kit components и position-centric таблиците `catalog_diagrams`/`catalog_position_hotspots`. Старият недостатъчен unique key за каталожна позиция се премахва, без да се изтриват исторически редове. Миграцията работи с PostgreSQL и SQLite. Guarded downgrade възстановява schema `0018` и `uq_part_catalog_source_position`, когато данните са съвместими; ако V2 source variants се сблъскват по legacy identity `brand/model/assembly/position/part_number`, downgrade отказва преди каквито и да е destructive промени, без merge, delete или загуба на history.

След `upgrade head` seed-ът валидира всички девет source файла и SHA-256 стойностите им, архивира старите active catalog/kit/document записи и идемпотентно импортира `PARTS_CATALOG_V2`. При липсващ или променен source bootstrap/read проверката fail-ва затворено. Docker image трябва да съдържа `backend/resources/technical_docs/PARTS_CATALOG/` и `backend/resources/catalog/v2/` непроменени.

Предходният `20260808_0016` добавя проследимите връзки от автоматично създаден ремонт към return transfer/document/batch, гарантира активния проверен справочен запис `Цех` и нормализира само текущия машинен статус: активно предаване → `ISSUED`, иначе незавършен ремонт → `REPAIR`, иначе `READY`. Audit, document, transfer и repair snapshot историята не се преписва.

`20260801_0006` добавя двуфазните `AWAITING_SIGNATURE` transfer операции, immutable signing hash, защита от повторен PNG подпис, snapshot полета за външните участници и връзка към точната template версия. Repair signature slots се деактивират, без да се изтрива историческа конфигурация. `20260801_0005` преди него добавя профилите, owner designation, лицензите и основата на official document/signature модела. Нито една миграция не допълва имена, длъжности или business history чрез догадки.

Production Docker image включва LibreOffice Writer за PDF от exact filled DOCX source, DejaVu fonts и PostgreSQL client за backup/restore. След deploy проверете `/api/health`, Alembic head, owner designation, licence status и restore в отделна база. Вижте `BACKUP_RESTORE_BG.md` и `RELEASE_CHECKLIST_BG.md`.

Предходният `20260731_0003_industrial_platform` добавя универсални asset категории/полета/файлове/събития, деактивируеми местоположения и триезични отдели, разширения ремонтен lifecycle, versioned templates/documents, multi-line requests и fulfillment, request attachments, provenance catalog/images/hotspots, kits, technical revisions и структурираните transfer/return полета. Миграцията добавя липсващи колони idempotent към legacy RC схема и създава новите таблици чрез общата SQLAlchemy metadata, така че да работи и върху fresh database, и върху историческа SQLite база.

Предходната `20260731_0002_i18n_status_roles` добавя `users.preferred_language`, преобразува само познатите legacy български статуси към стабилни кодове и оставя непознатите исторически стойности непроменени. И двете миграции са съвместими с PostgreSQL и SQLite и имат downgrade.

Production release sequence:

1. спрете/дренирайте пишещия трафик според платформата;
2. направете и проверете encrypted backup в отделно хранилище;
3. върху exact release image изпълнете еднократно `python -m app.runtime prepare`;
4. командата взема bounded PostgreSQL advisory lock, изпълнява `upgrade head`, canonical idempotent seed и source проверки; при lock timeout или грешка завършва non-zero;
5. стартирайте web процесите с `MIGRATION_STRATEGY=external`; те само проверяват schema/source/crypto/license state и не пишат миграции/seed;
6. насочете трафик едва след успешен `GET /api/ready`.

Само migration операция без bootstrap се изпълнява с `python -m app.migrations` или `python -m app.runtime migrate`. Не стартирайте паралелно гол Alembic CLI в production, защото заобикаля application advisory lock.

Read-only диагностиката се изпълнява с `PYTHONPATH=backend python backend/scripts/validate_official_document_integrity.py`. По подразбиране тя fail-ва само за release-blocking schema/canonical ambiguity и отчита непоправимата historical аномалия като `TOLERATED_HISTORY`; `--strict-history` е за отделен контролиран одит.

`backend/alembic/migration_history_manifest.json` пази normalized-LF SHA-256 за revisions `0001…0021`. Обикновеният `validate_migration_history()` и CLI без flag отказват променен/липсващ protected файл, но приемат и отчитат нова unprotected revision за диагностика по време на разработка. Това не означава разрешен release.

CI използва `python backend/scripts/validate_migration_history.py --require-all-protected`, а release verifier — същата строга проверка. Missing, mismatched или която и да е `new_unprotected_migrations` блокира merge/release кандидата с non-zero exit. Текущият baseline е **21 protected / 0 unprotected**.

Задължителният lifecycle е: създаване/редактиране на нов revision → завършване на реализацията и тестовете → normalized-LF SHA-256 → нов manifest entry **в същия PR** → strict CI → review/merge. Използвайте `normalized_sha256(Path(...))` от `backend.scripts.migration_history`: алгоритъмът заменя CRLF с LF преди SHA-256. Не е нужен следващ PR само за защита на вече merge-ната миграция. Публикуваните revisions и съществуващите hashes никога не се редактират или преизчисляват, за да прикрият промяна; schema корекции изискват нов revision.

Миграцията `20260731_0001_bulk_transfers` добавя партиди, активна връзка, return данни, protocol document snapshots и audit препратки. За PostgreSQL и SQLite се създава partial unique index за едно активно предаване на машина. Legacy SQLite схемата се backfill-ва според последното предаване и текущия статус, без промяна на машинния регистър.

Web lifespan изпълнява migration/seed само при `MIGRATION_STRATEGY=startup` (development/test и изрично staging). Production валидирането допуска само `external`; web процесът fail-ва преди трафик, ако отделната стъпка не е достигнала текущия head или source/catalog/crypto проверката е неуспешна.

Rollback е restore-first процедура: спрете пишещия трафик, запазете failed release log/code, върнете предходния application image и възстановете предварително проверения backup в отделна база за проверка. Alembic downgrade се допуска само след review на конкретната revision и втори backup. `0019 → 0018` е guarded: при несъвместими source variants завършва с ясно `Cannot downgrade PARTS_CATALOG_V2 to 0018 safely` преди промяна на schema и изисква предварително archive/export или контролирана миграция на references. Downgrade на final-role migration връща `director` към `manager` и `observer` към `viewer` и премахва новите owner/session колони; не го използвайте като обикновена production операция. По-старите downgrade стъпки могат да премахнат нови таблици/полета и да загубят transfer/document история.

## Docker

Runtime image работи с фиксиран непривилегирован UID/GID `10001:10001`, инсталира LibreOffice Writer, DejaVu и PostgreSQL client, а `/app` е read-only за runtime потребителя. LibreOffice използва изолиран профил под `/tmp`. Production-style Compose добавя `read_only`, tmpfs `/tmp`, `no-new-privileges` и `cap_drop: ALL`; CI доказва DOCX→PDF и readiness при тези ограничения.

PostgreSQL няма host `ports` в основния Compose файл и е достъпен само по вътрешната Compose мрежа. Ако операторът изрично се нуждае от локален development достъп, използвайте loopback-only override:

```bash
docker compose config
docker compose build
docker compose up
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Последната команда е само за development и публикува `127.0.0.1:5432`, не публичен интерфейс.

## Liveness и readiness

- `GET /api/health` е евтин liveness: доказва единствено, че ASGI процесът отговаря, и не докосва база, лиценз или source файлове.
- `GET /api/ready` е readiness и връща `200` само при ready runtime, работеща DB връзка, exact Alembic head, валидна production конфигурация, успешна cached startup catalog/source проверка, работеща document/signature crypto конфигурация и изпълнима license evaluation за активния режим.
- При проблем readiness връща `503` и само структурирани `status`/`code` стойности като `database_unavailable` или `database_schema_behind`; не връща URL, ключ, email, path или exception текст.
- Невалиден/изтекъл лиценз остава достъпен в съществуващия read-only workflow; readiness проверява, че оценката работи, без да блокира разрешените login/export/backup/license операции.

## След deployment

1. Проверете отделно `/api/health` и `/api/ready`; deployment health check трябва да сочи readiness.
2. Проверете чрез безопасен `/api/auth/me`, че има точно един активен `is_system_owner` с роля `administrator`; не отпечатвайте email или token в deployment log.
3. Проверете, че регистърът съдържа точно проверените 19 HPWJ машини.
4. Извършете контролирано издаване и връщане само с разрешени реални бизнес данни или в отделна тестова база.
5. Изтеглете DOCX, PDF и ZIP; проверете кирилицата и layout-а.
6. Проверете audit записа за success и контролирания 409 конфликт.
7. Отворете QR паспорт, ремонтна карта, каталог с provenance и version history на технически документ.
8. Активирайте и тествайте backup/restore процедурата на PostgreSQL.
