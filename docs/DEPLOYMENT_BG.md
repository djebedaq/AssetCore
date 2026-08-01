# Deployment и миграции

## Конфигурация

Задължителните продукционни environment variables са `DATABASE_URL`, `SECRET_KEY`, `ASSETCORE_OWNER_EMAIL` и `ADMIN_PASSWORD`. Локалният Docker Compose изисква и `POSTGRES_PASSWORD`; паролата в `DATABASE_URL` трябва да е URL-encoded. Не поставяйте стойностите им в Git, issue, log или screenshot. Render генерира `SECRET_KEY`, взема връзката от managed PostgreSQL и очаква ръчно зададени owner email и bootstrap admin парола. `ADMIN_EMAIL` е само fallback за legacy миграция и не замества новата owner конфигурация.

Generic Render URLs с `postgresql://` или legacy `postgres://` се нормализират към SQLAlchemy драйвера `postgresql+psycopg://`. SQLite URL остава непроменен.

## Миграция

Текущият `head` включва `20260801_0004_final_user_roles`. Преди schema промяна той изисква нормализираният `ASSETCORE_OWNER_EMAIL` да съвпада с точно един съществуващ акаунт при непразна база. След това мигрира legacy ролите, добавя owner/password/session timestamps и database ограниченията. Друг legacy admin се запазва като director с audit warning; никоя връзка към оперативна история не се променя. При невъзможно еднозначно определяне migration-ът прекратява работа преди DDL.

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
