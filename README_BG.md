# AssetCore Director Edition

AssetCore е responsive PWA система за проследимо управление на индустриални активи. Интерфейсът е пълен на български, английски и руски, като българският остава език по подразбиране. Backend-ът е FastAPI/SQLAlchemy, frontend-ът е React/TypeScript, локалната среда използва SQLite, а продукционната — PostgreSQL.

Източник на истина за активите е [SOURCE_REGISTER_BG.md](docs/SOURCE_REGISTER_BG.md). Seed данните съдържат точно 19 проверени HPWJ машини: CombiJet №4–5, Falch 1000 bar №7, 17–18, Falch 500 bar №9–16, собствено производство №19 и HYDWIN/Fussen №20–24. Не добавяйте демонстрационни машини или непотвърдена бизнес история.

## Основни възможности

- машинен регистър, статус, местоположение, QR и пълна история;
- единично и групово издаване със защита от двойно издаване;
- атомарно пълно и частично връщане по конкретно активно предаване;
- отделен DOCX и PDF протокол за всяка машина и ZIP за цялата партида;
- ремонтен поток, заявки за части и проверен каталог;
- съществуваща техническа библиотека и референтни ремонтни документи;
- неизменяем през нормалния API журнал на действията;
- миграции с Alembic, Docker, Render и GitHub Actions.
- устойчиви технически кодове за статусите, които се превеждат само в API/UI слоя;
- ролеви права за администратор, ръководител, механик, одобряващ и наблюдател.

## Езици, роли и статуси

Езикът се сменя от входния екран, заглавната лента или „Настройки“. Изборът се пази локално, а след вход — и в профила чрез `PATCH /api/users/me/preferences`. Клиентът изпраща `Accept-Language`; при липсващ или непознат език fallback-ът е български.

Статусите в базата и API са стабилни кодове (`READY`, `ISSUED`, `INSPECTION`, `REPAIR`, `TESTING` и други). Човешките имена се визуализират според избрания език. Старите български стойности се приемат за обратна съвместимост и миграция.

Ролевата матрица и архитектурните граници са описани в [I18N_AND_ROLES_BG.md](docs/I18N_AND_ROLES_BG.md) и [ARCHITECTURE_BG.md](docs/ARCHITECTURE_BG.md).

## Локален старт със SQLite

Изисквания: Python 3.12+, Node.js 22+ и pnpm 11.

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
Copy-Item backend/.env.example backend/.env
```

Задайте собствен дълъг `SECRET_KEY` и силна `ADMIN_PASSWORD` в `backend/.env`. Не записвайте `.env` в Git.

```powershell
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --reload
```

В отделен терминал:

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Интерфейсът е на `http://localhost:5173`, API документацията — на `http://localhost:8000/docs`. При старт backend-ът също прилага чакащите миграции преди seed проверката.

## Docker и PostgreSQL

Копирайте `.env.example` като `.env` в главната папка и задайте собствени стойности за `POSTGRES_PASSWORD`, URL-encoded `DATABASE_URL`, `SECRET_KEY`, `ADMIN_EMAIL` и `ADMIN_PASSWORD`, след което:

```powershell
docker compose up --build
```

Приложението е на `http://localhost:10000`. В `docker-compose.yml` няма записани пароли по подразбиране; липсващите задължителни стойности прекратяват старта с ясна грешка.

## Работа с групови предавания

От „Групово издаване“ операторът избира само налични машини, преглежда обобщението и потвърждава еднократно. Backend-ът валидира всички записи в една транзакция. При конфликт се връща HTTP 409 с номер, статус и наличната препратка към активно предаване; не се създава частична партида.

Всяка машина получава собствен проследим протокол. Резултатът предлага отделни DOCX/PDF файлове и общ ZIP. Файловете се изтеглят през удостоверен API и отговорите не разкриват вътрешни файлови пътища.

„Групово връщане“ показва само активните предавания. За всяка машина се въвеждат състояние, резултат, бележки и следващ етап. Връщането не я прави автоматично „Готова“: допустимият поток е „Връщане → Преглед → Почистване / Ремонт → Тестване → Готова за работа“. Частично върната партида остава отворена, докато всички нейни машини бъдат върнати.

Подробни инструкции: [OPERATIONS_BULK_TRANSFERS_BG.md](docs/OPERATIONS_BULK_TRANSFERS_BG.md). API договор: [API_BG.md](docs/API_BG.md). Deployment и миграции: [DEPLOYMENT_BG.md](docs/DEPLOYMENT_BG.md).

## Проверки

```powershell
backend/.venv/Scripts/python.exe -m pytest -q
backend/.venv/Scripts/python.exe -m compileall -q backend/app tests
backend/.venv/Scripts/python.exe -m ruff check backend/app tests
cd frontend
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

За legacy SQLite миграцията има интеграционен тест, който създава отделна временна база и проверява, че инвентарният и серийният номер остават непроменени.

## Документация

- [регистър на източниците](docs/SOURCE_REGISTER_BG.md)
- [проверен HPWJ инвентар](docs/HPWJ_INVENTORY_BG.md)
- [директорска демонстрация](docs/DIRECTOR_DEMO_BG.md)
- [приемателен checklist](docs/ACCEPTANCE_CHECKLIST_BG.md)
- [архитектура](docs/ARCHITECTURE_BG.md)
- [езици, статуси и роли](docs/I18N_AND_ROLES_BG.md)
- [пътна карта](docs/ROADMAP_BG.md)
- [история на промените](CHANGELOG_BG.md)

AssetCore остава release candidate. Преди продукционна употреба организацията трябва да потвърди ролите, политиката за архивиране и окончателния фирмен вид на генерираните протоколи.
