# AssetCore v12 — финална release и инфраструктурна проверка

Дата: 05.08.2026 г.

## Обхват

V12 не променя потвърдения регистър на 19-те HPWJ машини, ролите, owner designation, лицензирането, audit историята или вече създадените документи. Етапът финализира release автоматизацията и проверките след функционалните промени във v4–v11.

## Реализирани промени

- Версията е актуализирана до `1.3.0-rc.2`.
- PostgreSQL smoke test вече определя автоматично текущия Alembic head чрез `ScriptDirectory`, вместо да сравнява с остарял hardcoded revision.
- `backend/alembic.ini` използва `path_separator = os` за съвместимост с актуалните версии на Alembic.
- GitHub Actions workflow-ът вече съдържа отделни jobs за:
  - frontend install, typecheck, lint, tests и production build;
  - backend compile, Ruff, целия pytest пакет и release verifier;
  - PostgreSQL 16 миграции и криптиран backup/restore round trip между две изолирани тестови бази;
  - `docker compose config` и production Docker image build.
- Добавени са tests за CI покритието и динамичното определяне на Alembic head.
- Коригиран е стар тест, който е предполагал, че паспортът няма предварително внесени проверени технически документи. Тестът вече проверява, че новият документ присъства, без да отхвърля валидните seed документи.

## Реално изпълнени проверки

### Backend

- Python compile check — успешно.
- Събрани тестове — **132**.
- Изпълнени тестове — **132 passed**.
- Поради максималния лимит на единична shell команда тестовете са изпълнени в контролирани групи, а не в една непрекъсната `pytest -q` сесия.
- Release verifier — **21/21 проверки успешни**.
- Alembic upgrade върху чиста SQLite база до `20260805_0014` — успешно.
- Migration, inventory, roles, owner, signatures, catalog, backup/export и document hash проверки — успешно.

### Документи

- Document QA — успешно.
- Издаване и приемане — по една A4 страница.
- Няма unresolved placeholders.
- Кирилицата присъства правилно в DOCX и PDF.
- Подписите остават в основните полета.
- Оригиналните reference файлове са с непроменени SHA-256 стойности.
- Ремонтният протокол е вътрешен и не съдържа външни repair handover роли.

### Frontend

- TypeScript syntax/transpile проверка на всички 24 `.ts`/`.tsx` файла — успешно.
- Изолирана semantic TypeScript проверка на production source файловете — успешно.
- Реален dependency-backed `pnpm install`, typecheck, lint, Vitest и Vite build не можаха да бъдат изпълнени в текущата среда:
  - Corepack: `EAI_AGAIN registry.npmjs.org`;
  - вътрешният npm registry: HTTP 404 за необходимите пакети.
- Пълните frontend проверки са конфигурирани като задължителен GitHub Actions job.

### Docker и PostgreSQL

- Dockerfile, Compose YAML и CI workflow са валидирани статично — успешно.
- В текущата среда липсват `docker`, `psql`, `postgres`, `pg_dump` и `pg_restore`, затова реалният container/full-stack и PostgreSQL round-trip не са представени като локално успешни.
- И двете проверки са добавени като отделни CI jobs и трябва да бъдат зелени преди merge към production branch.

## Release оценка

- Готова за разработка: **Да**.
- Готова за локални тестове: **Да**.
- Готова за staging: **Да, като release candidate след зелени GitHub CI jobs**.
- Готова за ограничен пилот: **Само след успешни frontend, Docker и PostgreSQL CI проверки и staging smoke test**.
- Готова за production: **Не се декларира преди зелени CI проверки, реален staging deployment, backup/restore rehearsal и организационно одобрение**.

## GitHub workflow

Поради отказан write достъп на GitHub интеграцията (`403 Resource not accessible by integration`) версията се предоставя като чист ZIP и patch. Branch, commit SHA, Pull Request и merge commit ще бъдат създадени от собственика при качването в `djebedaq/AssetCore`.
