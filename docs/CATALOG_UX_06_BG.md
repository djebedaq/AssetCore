# CATALOG-UX-06 — Централизирано управление на каталози

## Обобщение

Разделът „Управление на каталози“ запазва route/identifier `catalogBuilder`, правото
`parts.manage` и каталожния конструктор от UX05. В менюто е непосредствено след
„Каталог резервни части“, с отделна икона `LibraryBig`. Основният панел съдържа
видими съседни действия „Свържи каталог“ и „Нов каталог“.

Един компонент `CatalogBindings` обслужва изгледите „Свързване“ и „Активни връзки“.
Същият прозорец се отваря и от конкретен каталог с предварително избран каталог.
Старите редактори `MachineCatalogLinks` и `WizardMachines` са премахнати, както и
входовете им от „Машини“, `IndustrialCatalog`, `SimpleCatalogBuilder` и
`CatalogMaintenance`. Последният запазва read-only списък и отваря общия редактор.
`ReferenceLinker`/`SharedReferences` управляват технически референции чрез отделния
договор `CatalogReferenceAssociation`; тази функционалност е запазена.

## Архитектура и права

`backend/app/catalog_admin/bindings.py` съдържа общите проекции, preview и
транзакционни операции. Съществуващите single endpoints са запазени за валидни API
клиенти, но делегират на същия service. Всички нови HTTP endpoints използват
съществуващия backend dependency за `parts.manage`. Frontend също проверява правото.

Не са добавяни зависимости, нови роли, schema промени или data migration. Не са
променяни verified inventory, source register, бинарни документи или публикации.

## API договор

Всички пътища по-долу започват с `/api/admin/catalog-builder`.

| Метод и път | Предназначение |
| --- | --- |
| `GET /bindings/machines` | Машини по категория, търсене и изрично странициране |
| `GET /bindings` | Активни и чакащи връзки, филтри и версия за премахване |
| `POST /bindings/preview` | Проверка на цялата селекция, причини и digest |
| `POST /bindings/batch` | Един атомарен bind/reactivate за целия списък |
| `POST /bindings/batch-deactivate` | Едно атомарно soft-deactivate за конкретни връзки |
| `POST /catalogs/{catalog_id}/assets/{machine_id}` | Съвместим single API със същите правила |
| `DELETE /catalogs/{catalog_id}/assets/{machine_id}` | Съвместим single API за деактивиране |

Read endpoints приемат `offset` (>= 0), `limit` (1–100, default 50), `search` (до
120 знака), `category_id`, `catalog_id`; списъкът с връзки приема и `machine_id`.
Отговорът е `{items, total, offset, limit}`. Търсенето на машини включва inventory,
име, brand, model и serial; `%`/`_` се търсят буквално. Няма скрито отсичане на
резултатите. Селекцията се пази между страниците/филтрите. „Избери всички“ обхваща
само показаната страница, с изрично описание. Максимумът от 500 връзки на операция
е показан в UI и се валидира от backend.

Preview/bind request:

```json
{
  "catalog_id": 101,
  "machine_ids": [201, 202],
  "confirmed_machine_ids": [202]
}
```

Това са примерни технически идентификатори, а не бизнес записи. ID полетата са
строги положителни integers; bool, strings, дублирани IDs, празни/твърде големи
групи и confirmations извън селекцията се отхвърлят с 422. Preview връща
`{catalog_id, published_revision, machines, ready, digest}`. Всеки machine ред
съдържа identity, compatibility, confirmation и конкретен blocking `code`.
За batch запис се изпраща същият request с `expected_digest` от актуалния preview.
Липсващ или променен digest се отказва с `catalog_bindings_stale` (409).

Успешен bind връща 201 с `{operation_id, catalog_id, published_revision, count,
machines}`; всеки резултат съдържа `binding_id` и machine identity. `count` включва
новите и защитено повторно активираните двойки. Няма частичен success.

Batch removal request:

```json
{
  "bindings": [
    {
      "binding_id": 301,
      "catalog_id": 101,
      "machine_id": 201,
      "expected_digest": "<64 hex characters from the binding list>"
    }
  ]
}
```

Всяка двойка трябва да съвпада с конкретния активен binding. Успехът връща 200 с
`{operation_id, count, binding_ids}`. Липсваща/неактивна връзка, подправена двойка
или остарял digest отказва цялата група. UI показва точния списък в същия прозорец
и изисква изрично потвърждение. Няма вложен confirmation modal.

## Compatibility и publication

Използва се съществуващата NFKC/casefold normalization и договор:

- `EXACT`: налични и съвпадащи производител и модел; без ръчно потвърждение.
- `AMBIGUOUS`: липсващи данни или частично моделно означение; отделна отметка за
  всяка конкретна машина, включена в `confirmed_machine_ids`.
- `INCOMPATIBLE`: установено несъответствие; confirmation не може да го заобиколи.

Категорията трябва да е активна и да има `HAS_PARTS_CATALOG`; машина и каталог
трябва да принадлежат към същата категория. Машината и каталогът трябва да са
активни. Нова връзка изисква текущ `PUBLISHED` revision. Нова чернова REV-2 не
пречи на свързването чрез публикувана REV-1. Вече активна двойка се отказва,
включително при остаряла заявка. Една машина запазва множество каталози.

Основни error codes: `catalog_not_published`, `catalog_bindings_stale`,
`catalog_asset_already_bound`, `catalog_asset_not_found`, `catalog_asset_inactive`,
`catalog_inactive`, `catalog_category_inactive`, `catalog_category_not_supported`,
`catalog_asset_category_mismatch`, `catalog_asset_model_mismatch`,
`catalog_asset_compatibility_confirmation_required`, `catalog_asset_binding_not_found`.
Отказан bind включва `issues` с конкретните машини и причини. BG/EN/RU са с key parity.

## Транзакции и locking

Всяка batch операция има един commit, само след пълна валидация и подготовка на
всички записи и audit събития. Всяко изключение връща цялата транзакция назад,
включително грешка при flush, audit или commit. Single wrappers не правят
самостоятелни допълнителни commits и не се извикват в цикъл от batch service.

Детерминиран ред:

1. Всички машини по възходящ ID (`FOR UPDATE`).
2. Всички каталози по възходящ ID чрез съществуващия `lock_catalog`.
3. Категориите по възходящ ID (`FOR SHARE`).
4. При премахване — конкретните bindings по възходящ ID (`FOR UPDATE`).

Машинните identity редакции вземат shared catalog locks преди category locks.
Това премахва обратния ред спрямо binding/catalog mutations. Catalog edits и
publication запазват canonical catalog lock и не заключват машини в обратен ред.
След изчакване се правят authoritative reads с `populate_existing`, включително
на категория, публикация, machine identity/activity и текущ binding state.
SQLite взема write lock преди тези проверки. Unique constraint за
`(catalog_id, machine_id)` остава последната DB защита и на двата engine-а.

Bind digest обхваща каталога, категорията, текущата публикация и конкретните
машини/потвърждения. Removal digest включва identity, state, publication и последния
audit ID за конкретната връзка. Така unbind/rebind цикълът (ABA) променя generation,
без да променя първоначалния binding ID или created_at и без нова DB колона.
След stale error UI изисква нова селекция и review, вместо да подменя тихо digests.

Проекциите използват joins, grouped audit aggregation и групови четения; няма
заявка за всеки ред в новите списъци. Catalog counts се изчисляват групово.

## Legacy pending и история

Старите активни връзки към непубликувани каталози остават със същите IDs, timestamps
и audit history. Показват се като `PENDING_PUBLICATION` / „Очаква публикация“ и се
броят отделно от връзките с текуща публикация. Могат да се премахват контролирано.
Runtime продължава да избира само публикувани ревизии; черновите не предоставят
части, схеми или комплекти. След първа валидна публикация действа съществуващият
runtime договор. Нови pending връзки са забранени през всички binding write paths.

Премахването променя само `is_active` и `deactivated_at`. Не се изтриват дефиниции,
ревизии, parts, PDF, hotspots, kits, requests, документи, snapshots или audit.
Повторното свързване активира съществуващата двойка, запазвайки нейния ID и
първоначалното създаване. Audit `CATALOG_ASSET_BOUND`/`CATALOG_ASSET_UNBOUND` пази
оператор, timestamp, catalog/machine, compatibility и индивидуално потвърждение
при bind, общ UUID в details и в съществуващото поле `operation_reference`.

## Проверки и доказателства

Окончателните точни резултати и screenshot manifest ще бъдат добавени след
приключване на локалните проверки и GitHub CI. Неприключил тест не е PASS.

Добавени са backend HTTP/service tests, fault injection след подготвени редове,
audit/commit rollback, stale/ABA и pair spoof проверки, pagination >100 машини,
EXACT/AMBIGUOUS/INCOMPATIBLE, права, legacy pending и multiple-catalog coverage.
Реалните PostgreSQL тестове използват отделен временен контейнер без host ports,
tmpfs база и независими sessions с доказано изчакване на row locks. Frontend
Vitest покрива селекцията, preview, индивидуални confirmations, една batch заявка,
премахване по binding ID, stale errors, focus/close guard и translations.

Browser runner: `python tests/browser/run_catalog_ux06_qa.py` с наличен Playwright.
Създава нова SQLite база и loopback ephemeral port в `.tmp`; credentials са случайни,
само в process environment. Не записва auth state/HAR/tokens в доказателствата.
CI изпълнява UX04, UX05 и UX06 browser scenarios, както и пълните backend,
PostgreSQL, frontend, security, migration и Docker jobs.

## Production защита

Разработката е само в изрично разрешената development директория. Не са използвани
production директорията, credentials, база или backups. Не са изпълнявани deploy
или production manager команди. QA Docker ресурсите имат собствени имена и tmpfs;
няма общ cleanup, production port binding или промяна на работещи услуги.

## Независим review преди merge

- Проверете lock order спрямо machine identity edits, category administration,
  publication, runtime request reads и owner-only destructive paths.
- Проверете гаранцията за rollback и audit при изключение след flush/на commit.
- Проверете digest invalidation и ABA отказа, включително различни каталози на
  една машина и legacy pending bindings без предишно audit събитие.
- Проверете запазването на историческите snapshots/documents и UX05 optional warnings.
- Проверете responsive screenshots, keyboard focus, индивидуални confirmations,
  selection persistence и изричните page/batch limits.
- Проверете точните CI резултати и окончателния diff за verified business material.

Merge и deployment остават отделни, изрично неодобрени действия в тази задача.
