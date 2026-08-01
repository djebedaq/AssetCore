# Промени

## Universal industrial platform — 2026-07-31

- Добавени са универсални asset категории, configurable passport fields, attachments, QR web passport и immutable machine timeline.
- Добавен е пълен валидиран repair lifecycle с inspection/cleaning/test completion gates, събития, използвани части, снимки и отделни DOCX/PDF протоколи.
- Добавени са multi-line part requests, проследимо submit/approval решение и immutable versioned документи.
- Разширен е каталогът с provenance, confidence, verification, изображения, алтернативни номера/заместители, визуални hotspots и human-approved repair kits.
- Техническата библиотека вече пази SHA-256 и всяка revision; добавено е глобално търсене.
- Добавени са versioned BG/EN/RU document templates, generated-document snapshots и QA generator за сравнение със съществуващите снимкови/DOCX образци.
- Добавени са admin operations за users/roles, categories/fields, деактивируеми местоположения, триезични отдели, templates и signed two-step import със защита на verified HPWJ регистъра.
- Добавени са свързани ремонти и файлови приложения към заявките за части, както и директно пренасяне на машината от паспорта към заявка през каталога.
- Добавен е responsive BG/EN/RU frontend за всички нови workflows и API/миграционни/integration тестове.

## Industrial foundation — 2026-07-31

- Добавена е централизирана многоезична архитектура с пълни `bg`, `en` и `ru` каталози, български fallback, локално и профилно запазване на езика и locale-aware дати/числа.
- Премахнат е hardcoded потребителският текст от React компонентите; добавени са езиков превключвател, parity/fallback/persistence тестове и localized conflict представяне без raw backend грешки.
- Машинните, batch, ремонтните и request статусите вече използват стабилни технически кодове; UI превежда кодовете, а API приема и legacy български стойности за съвместимост.
- Добавена е обратима Alembic migration `20260731_0002_i18n_status_roles`, която пази непознатите исторически стойности и добавя `users.preferred_language`.
- Ролите са разширени до `admin`, `mechanic`, `manager`, `approver` и `viewer` с backend проверки според операцията.
- Seed логиката вече не изтрива потребителски активи или бъдещи категории; провереният 19-машинен HPWJ регистър остава непроменен.
- Премахнати са предварително попълнените login credentials и автоматично измисленият резултат при приключване на ремонт; реалният тестов резултат вече е задължителен.

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
