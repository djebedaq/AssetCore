# Deployment и миграции

## Конфигурация

Задължителните продукционни environment variables са `DATABASE_URL`, `SECRET_KEY`, `OWNER_FIRST_NAME`, `OWNER_MIDDLE_NAME`, `OWNER_LAST_NAME`, `OWNER_EMAIL`, `OWNER_JOB_TITLE`, стабилен `INSTALLATION_ID`, `LICENSE_PUBLIC_KEY` и отделен `SIGNATURE_ENCRYPTION_KEY`. `OWNER_INITIAL_PASSWORD` е задължителна само при първия bootstrap върху база без потребители; след успешния вход и forced password change я премахнете от environment-а. Задайте `PRODUCTION_MODE=true` и `LICENSE_ENFORCEMENT_ENABLED=true`. Локалният Docker Compose изисква и `POSTGRES_PASSWORD`; паролата в `DATABASE_URL` трябва да е URL-encoded. Не поставяйте стойностите им в Git, issue, log или screenshot. `ASSETCORE_OWNER_EMAIL`/`ADMIN_*` остават само като legacy migration compatibility и не са новият bootstrap договор.

Generic Render URLs с `postgresql://` или legacy `postgres://` се нормализират към SQLAlchemy драйвера `postgresql+psycopg://`. SQLite URL остава непроменен.

## Миграция

Текущият `head` е `20260826_0020`. Той добавя unique owner key за `OfficialDocumentVersion`, PostgreSQL composite FK `official_documents(id, current_version_id) → official_document_versions(document_id, id)` и version-side trigger, както и SQLite trigger еквивалент. Преди guard-а миграцията отчита само броя на NULL, missing, wrong-owner, shared и orphan historical състояния. Тя не променя pointer, snapshot, binary document, signature или hash данни; PostgreSQL constraint се добавя `NOT VALID` и се валидира автоматично само когато existing current pointers са съвместими. Новите writes се пазят и при tolerated historical anomalies.

Предходният `20260818_0019` добавя source identity/metadata към `part_catalog`, active/source metadata към technical documents и repair kits, source metadata към kit components и position-centric таблиците `catalog_diagrams`/`catalog_position_hotspots`. Старият недостатъчен unique key за каталожна позиция се премахва, без да се изтриват исторически редове. Миграцията работи с PostgreSQL и SQLite. Guarded downgrade възстановява schema `0018` и `uq_part_catalog_source_position`, когато данните са съвместими; ако V2 source variants се сблъскват по legacy identity `brand/model/assembly/position/part_number`, downgrade отказва преди каквито и да е destructive промени, без merge, delete или загуба на history.

След `upgrade head` seed-ът валидира всички девет source файла и SHA-256 стойностите им, архивира старите active catalog/kit/document записи и идемпотентно импортира `PARTS_CATALOG_V2`. При липсващ или променен source bootstrap/read проверката fail-ва затворено. Docker image трябва да съдържа `backend/resources/technical_docs/PARTS_CATALOG/` и `backend/resources/catalog/v2/` непроменени.

Предходният `20260808_0016` добавя проследимите връзки от автоматично създаден ремонт към return transfer/document/batch, гарантира активния проверен справочен запис `Цех` и нормализира само текущия машинен статус: активно предаване → `ISSUED`, иначе незавършен ремонт → `REPAIR`, иначе `READY`. Audit, document, transfer и repair snapshot историята не се преписва.

`20260801_0006` добавя двуфазните `AWAITING_SIGNATURE` transfer операции, immutable signing hash, защита от повторен PNG подпис, snapshot полета за външните участници и връзка към точната template версия. Repair signature slots се деактивират, без да се изтрива историческа конфигурация. `20260801_0005` преди него добавя профилите, owner designation, лицензите и основата на official document/signature модела. Нито една миграция не допълва имена, длъжности или business history чрез догадки.

Production Docker image включва LibreOffice Writer за PDF от exact filled DOCX source, DejaVu fonts и PostgreSQL client за backup/restore. След deploy проверете `/api/health`, Alembic head, owner designation, licence status и restore в отделна база. Вижте `BACKUP_RESTORE_BG.md` и `RELEASE_CHECKLIST_BG.md`.

Предходният `20260731_0003_industrial_platform` добавя универсални asset категории/полета/файлове/събития, деактивируеми местоположения и триезични отдели, разширения ремонтен lifecycle, versioned templates/documents, multi-line requests и fulfillment, request attachments, provenance catalog/images/hotspots, kits, technical revisions и структурираните transfer/return полета. Миграцията добавя липсващи колони idempotent към legacy RC схема и създава новите таблици чрез общата SQLAlchemy metadata, така че да работи и върху fresh database, и върху историческа SQLite база.

Предходната `20260731_0002_i18n_status_roles` добавя `users.preferred_language`, преобразува само познатите legacy български статуси към стабилни кодове и оставя непознатите исторически стойности непроменени. И двете миграции са съвместими с PostgreSQL и SQLite и имат downgrade.

```bash
python -m alembic -c backend/alembic.ini upgrade head
```

Read-only диагностиката се изпълнява с `PYTHONPATH=backend python backend/scripts/validate_official_document_integrity.py`. По подразбиране тя fail-ва само за release-blocking schema/canonical ambiguity и отчита непоправимата historical аномалия като `TOLERATED_HISTORY`; `--strict-history` е за отделен контролиран одит.

`backend/alembic/migration_history_manifest.json` пази normalized-LF SHA-256 за вече публикуваните revisions `0001…0019`. `backend/scripts/validate_migration_history.py` се изпълнява автоматично в CI и release verifier, отказва променен или липсващ protected файл и разрешава нова revision. След като нова миграция бъде merge-ната, приложена и обявена за released, нейният normalized-LF hash се добавя като нов protected entry в отделна контролирана промяна; съществуващ hash никога не се преизчислява, за да прикрие редакция.

Миграцията `20260731_0001_bulk_transfers` добавя партиди, активна връзка, return данни, protocol document snapshots и audit препратки. За PostgreSQL и SQLite се създава partial unique index за едно активно предаване на машина. Legacy SQLite схемата се backfill-ва според последното предаване и текущия статус, без промяна на машинния регистър.

Вграденото приложение изпълнява `upgrade head` в lifespan преди seed проверката. В production се препоръчва и отделна pre-deploy миграционна стъпка, когато платформата я поддържа, за да се вижда резултатът преди трафик.

Rollback е описан във всяка Alembic revision, но преди downgrade направете валидиран backup. `0019 → 0018` е guarded: при несъвместими source variants завършва с ясно `Cannot downgrade PARTS_CATALOG_V2 to 0018 safely` преди промяна на schema и изисква предварително archive/export или контролирана миграция на references. Downgrade на final-role migration връща `director` към `manager` и `observer` към `viewer` и премахва новите owner/session колони; не го използвайте като обикновена production операция. По-старите downgrade стъпки могат да премахнат нови таблици/полета и да загубят transfer/document история.

## Docker

Runtime image инсталира DejaVu шрифтове за коректен кирилски PDF. `docker-compose.yml` изисква secrets чрез `.env` и не съдържа работещи пароли по подразбиране.

```bash
docker compose config
docker compose build
docker compose up
```

## След deployment

1. Проверете `/api/health` и приложената Alembic revision.
2. Проверете чрез безопасен `/api/auth/me`, че има точно един активен `is_system_owner` с роля `administrator`; не отпечатвайте email или token в deployment log.
3. Проверете, че регистърът съдържа точно проверените 19 HPWJ машини.
4. Извършете контролирано издаване и връщане само с разрешени реални бизнес данни или в отделна тестова база.
5. Изтеглете DOCX, PDF и ZIP; проверете кирилицата и layout-а.
6. Проверете audit записа за success и контролирания 409 конфликт.
7. Отворете QR паспорт, ремонтна карта, каталог с provenance и version history на технически документ.
8. Активирайте и тествайте backup/restore процедурата на PostgreSQL.
