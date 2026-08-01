# Deployment и миграции

## Конфигурация

Задължителните продукционни environment variables са `DATABASE_URL`, `SECRET_KEY`, `OWNER_FIRST_NAME`, `OWNER_MIDDLE_NAME`, `OWNER_LAST_NAME`, `OWNER_EMAIL`, `OWNER_JOB_TITLE`, стабилен `INSTALLATION_ID`, `LICENSE_PUBLIC_KEY` и отделен `SIGNATURE_ENCRYPTION_KEY`. `OWNER_INITIAL_PASSWORD` е задължителна само при първия bootstrap върху база без потребители; след успешния вход и forced password change я премахнете от environment-а. Задайте `PRODUCTION_MODE=true` и `LICENSE_ENFORCEMENT_ENABLED=true`. Локалният Docker Compose изисква и `POSTGRES_PASSWORD`; паролата в `DATABASE_URL` трябва да е URL-encoded. Не поставяйте стойностите им в Git, issue, log или screenshot. `ASSETCORE_OWNER_EMAIL`/`ADMIN_*` остават само като legacy migration compatibility и не са новият bootstrap договор.

Generic Render URLs с `postgresql://` или legacy `postgres://` се нормализират към SQLAlchemy драйвера `postgresql+psycopg://`. SQLite URL остава непроменен.

## Миграция

Текущият `head` е `20260801_0005`: отделни профилни полета, owner designation, лицензи, външни подписващи, участници, подписни позиции/сесии, криптографски metadata, official document versions и template validation. `20260801_0004_final_user_roles` преди него изисква нормализираният legacy owner email да съвпада с точно един съществуващ акаунт при непразна база. Нито една миграция не допълва имена, длъжности или business history чрез догадки.

Production Docker image включва LibreOffice Writer за PDF от exact filled DOCX source, DejaVu fonts и PostgreSQL client за backup/restore. След deploy проверете `/api/health`, Alembic head, owner designation, licence status и restore в отделна база. Вижте `BACKUP_RESTORE_BG.md` и `RELEASE_CHECKLIST_BG.md`.

Предходният `20260731_0003_industrial_platform` добавя универсални asset категории/полета/файлове/събития, деактивируеми местоположения и триезични отдели, разширения ремонтен lifecycle, versioned templates/documents, multi-line requests и fulfillment, request attachments, provenance catalog/images/hotspots, kits, technical revisions и структурираните transfer/return полета. Миграцията добавя липсващи колони idempotent към legacy RC схема и създава новите таблици чрез общата SQLAlchemy metadata, така че да работи и върху fresh database, и върху историческа SQLite база.

Предходната `20260731_0002_i18n_status_roles` добавя `users.preferred_language`, преобразува само познатите legacy български статуси към стабилни кодове и оставя непознатите исторически стойности непроменени. И двете миграции са съвместими с PostgreSQL и SQLite и имат downgrade.

```bash
python -m alembic -c backend/alembic.ini upgrade head
```

Миграцията `20260731_0001_bulk_transfers` добавя партиди, активна връзка, return данни, protocol document snapshots и audit препратки. За PostgreSQL и SQLite се създава partial unique index за едно активно предаване на машина. Legacy SQLite схемата се backfill-ва според последното предаване и текущия статус, без промяна на машинния регистър.

Вграденото приложение изпълнява `upgrade head` в lifespan преди seed проверката. В production се препоръчва и отделна pre-deploy миграционна стъпка, когато платформата я поддържа, за да се вижда резултатът преди трафик.

Rollback е описан във всяка Alembic revision, но преди downgrade направете валидиран backup. Downgrade на final-role migration връща `director` към `manager` и `observer` към `viewer` и премахва новите owner/session колони; не го използвайте като обикновена production операция. По-старите downgrade стъпки могат да премахнат нови таблици/полета и да загубят transfer/document история.

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
