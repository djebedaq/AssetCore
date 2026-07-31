# Deployment и миграции

## Конфигурация

Задължителните продукционни environment variables са `DATABASE_URL`, `SECRET_KEY`, `ADMIN_EMAIL` и `ADMIN_PASSWORD`. Локалният Docker Compose изисква и `POSTGRES_PASSWORD`; паролата в `DATABASE_URL` трябва да е URL-encoded. Не поставяйте стойностите им в Git, issue, log или screenshot. Render генерира `SECRET_KEY`, взема връзката от managed PostgreSQL и очаква ръчно зададена admin парола.

Generic Render URLs с `postgresql://` или legacy `postgres://` се нормализират към SQLAlchemy драйвера `postgresql+psycopg://`. SQLite URL остава непроменен.

## Миграция

```bash
python -m alembic -c backend/alembic.ini upgrade head
```

Миграцията `20260731_0001_bulk_transfers` добавя партиди, активна връзка, return данни, protocol document snapshots и audit препратки. За PostgreSQL и SQLite се създава partial unique index за едно активно предаване на машина. Legacy SQLite схемата се backfill-ва според последното предаване и текущия статус, без промяна на машинния регистър.

Вграденото приложение изпълнява `upgrade head` в lifespan преди seed проверката. В production се препоръчва и отделна pre-deploy миграционна стъпка, когато платформата я поддържа, за да се вижда резултатът преди трафик.

Rollback е описан в Alembic revision, но преди downgrade направете валидиран backup. Downgrade премахва новите таблици/полета и би загубил новата transfer/document история.

## Docker

Runtime image инсталира DejaVu шрифтове за коректен кирилски PDF. `docker-compose.yml` изисква secrets чрез `.env` и не съдържа работещи пароли по подразбиране.

```bash
docker compose config
docker compose build
docker compose up
```

## След deployment

1. Проверете `/api/health` и приложената Alembic revision.
2. Влезте с отделно предоставени credentials.
3. Проверете, че регистърът съдържа точно проверените 19 HPWJ машини.
4. Извършете контролирано издаване и връщане само с разрешени реални бизнес данни или в отделна тестова база.
5. Изтеглете DOCX, PDF и ZIP; проверете кирилицата и layout-а.
6. Проверете audit записа за success и контролирания 409 конфликт.
7. Активирайте и тествайте backup/restore процедурата на PostgreSQL.
