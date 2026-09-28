# CATALOG-ADMIN-01A: основа на Каталожния конструктор

## Граница спрямо проверения каталог

`PARTS_CATALOG_V2` остава единственият runtime каталог. Неговите 611 реда, седем ремонтни комплекта, 12 diagram страници, hotspot-и, технически файлове и immutable PARTS-DOC snapshots не се мигрират и не се представят като Builder записи. Екранът за каталог на машината продължава да чете `backend/app/catalog/` и контролирания manifest. Новият `backend/app/catalog_admin/` обслужва само административни чернови. В 01A няма upload, редактор за части или публикация.

## Данни и съвместимост

- `CatalogDefinition` е логически каталог с постоянен уникален код, задължителни BG/EN/RU имена, категория с `HAS_PARTS_CATALOG`, статус на активност и незадължителни описателни manufacturer/model стойности. Кодът е неизменяем. Категорията може да се сменя само преди първа ревизия или връзка.
- `CatalogRevision` принадлежи на Definition и има уникален за каталога неномериран `revision_code`. В 01A се създава само `DRAFT`; редактира се само бележката на чернова. `PUBLISHED`, `RETIRED` и полетата за публикация са резервирани за бъдещото валидирано публикуване. Няма publish API.
- `CatalogAssetBinding` е изрична връзка `CatalogDefinition → Machine`. Един каталог може да се свърже с много машини. Уникалният индекс по `machine_id` допуска най-много един Builder каталог за машина. Съвместимостта зависи само от равенството на `category_id`, активността и capability на категорията. Нито марка, модел, инвентарен номер, налягане, файл, HPWJ код или `machine_family()` се използва за Builder решение.

Неактивен каталог остава видим с ревизиите и връзките си, но не приема нова ревизия или връзка. Съществуваща връзка защитава категорията на машината; съществуващ Builder каталог защитава `HAS_PARTS_CATALOG` capability на категорията. Builder изтриване на връзка е допустимо само преди публикувана ревизия. Активен runtime каталог не се избира по тези Builder връзки.

## Транзакции и права

Всички Builder маршрути изискват `parts.manage` от backend dependency graph. Няма отделно право. POST/PATCH/DELETE валидират домейна и записват audit в същата транзакция. При свързване PostgreSQL заключва реда на машината; database unique constraint върху `machine_id` е последният арбитър при конкуренция. Integrity конфликт се превръща в контролиран HTTP 409. SQLite използва същото ограничение за локална работа. Маршрутите връщат технически кодове за грешка без SQL детайли.

Собственикът може да прегледа безопасно постоянно изтриване на `catalog_definition`: preview показва броя собствени чернови и връзки. Публикувана/оттеглена ревизия или външна защитена зависимост блокира изтриването. Изпълнението използва съществуващите owner reauthentication, точна фраза, dependency locks и audit, после премахва само Builder децата и Definition в една транзакция. Обикновен администратор няма този достъп. `PartCatalog` не е owner-deletable.

## Следващи етапи

Нормализирана бъдеща йерархия: `CatalogDefinition → CatalogRevision → assembly/source node → visual sources → parts → hotspots/repair kits`. Не се съхранява бъдещата структура в JSON конфигурация.

- **01B:** revision assemblies, технически upload, страници/preview, роли `EXPLODED_SCHEME` и `SPARE_PARTS_LIST`.
- **01C:** редактор/импорт на части, позиции и съпоставяне към списък и страници, човешка проверка на произход.
- **01D:** интерактивни hotspots, позиционни mappings, комплекти и визуална проверка.
- **01E:** publish validation, immutable публикация, атомичен runtime избор чрез изрична връзка и текуща публикувана ревизия, provenance-aware регистрация на V2, clone-next-revision и пълна PARTS-DOC интеграция.

При 01E visual records трябва да ползват съществуващите `CatalogVisualSource` (`source_id`, `catalog_revision`, `technical_document_id`, `page_number`, `role`, `source_sha256`) и `CatalogVisualPartMap` (`visual_source_id`, `part_id`). Не се създава конкуриращ role модел. Оригинални DOCX/PDF, audit и document history се запазват.
