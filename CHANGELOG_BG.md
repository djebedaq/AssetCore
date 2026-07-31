# Промени

## Bulk transfers and issue guards — 2026-07-31

- Добавена е авторитетна active-transfer връзка и database partial unique защита срещу двойно издаване.
- Груповото издаване валидира и записва всички машини атомарно с обща детерминирана batch препратка.
- Всяка машина получава отделно проследимо предаване и immutable DOCX/PDF snapshot; наличен е общ ZIP.
- Добавено е атомарно групово, частично и mixed-batch връщане с индивидуално състояние, резултат и бележки.
- Връщането води към преглед/почистване/ремонт/тест и не задава автоматично „Готова“.
- Разширен е audit журналът за успешни и отхвърлени операции, предишен/нов статус и местоположение и всички препратки.
- Добавени са Alembic миграция, PostgreSQL locking, SQLite-safe serialization и structured Bulgarian API errors.
- Добавен е пълен български responsive frontend workflow, PWA manifest/service worker и authenticated downloads.
- Добавени са backend integration/concurrency/migration/document tests и frontend component/conflict/confirmation/progress tests.
- Docker runtime включва кирилски PDF шрифт, а example/Docker secrets вече не съдържат работещи стойности по подразбиране.
- Провереният HPWJ инвентар, seed данните, QR функционалността и съществуващата техническа библиотека са запазени.

## Director Preview

- Премахнати са бояджийски и измислени демонстрационни активи.
- Възстановен е провереният HPWJ регистър с марки, модели, налягания и налични серийни номера.
- Добавени са приемо-предавателни протоколи, техническа библиотека, каталог, audit журнал и фирмен интерфейс.
