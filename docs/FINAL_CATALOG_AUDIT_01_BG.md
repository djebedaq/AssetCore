# FINAL-CATALOG-AUDIT-01 — Catalog Builder 01A–01E

Авторитетна база: `b5515081025042a557f1ae54dc4433681ed6ad44`.
Работен клон: `assetcore-final-catalog-audit`, създаден от тази точна база.
Дата на одита: 30.09.2026 г.

**Текущ статус: NOT READY FOR PRODUCTION.** Поправки са необходими. Докладът е
предварителен до завършването на пълните backend/PostgreSQL, Docker, PARTS-DOC и
backup/restore проверки и последващия review на единствения fix PR.
Незавършените проверки по-долу не се считат за успешни.

Продукционната инсталация не е отваряна, променяна, рестартирана или използвана
за тестовете. Няма deployment, merge, промени на продукционна конфигурация,
четене на продукционни secrets или записване на демонстрационни данни в
продукционна/committed база. Всички QA записи са във временни изолирани бази.
Първоначалният checkout и неговите съществуващи непубликувани файлове са запазени.

## Система и граници

`AssetCategory/HAS_PARTS_CATALOG → CatalogDefinition → CatalogRevision →
Assembly → Artifact/PDF bytes → explicit VisualPage roles → Parts/page maps →
verified position hotspots → Repair Kits/components` е control plane.

`CatalogAssetBinding(machine_id UNIQUE) → единствената PUBLISHED ревизия →
PartCatalog, TechnicalDocument/Revision, CatalogVisualSource/PartMap,
CatalogDiagram/PositionHotspot, RepairKit/Component` е runtime plane.
Публикуването материализира вече съществуващия operational модел. Builder не
създава втори механизъм за заявки, ремонти, snapshots или официални документи.
Builder lineage е чрез изрични FK полета; `CBR…`, `CBP…`, `CBH…` са допълнителни
идентификатори, които не заменят тези отношения.

При runtime обвързването и текущата PUBLISHED ревизия са авторитетни. V2
manifest-ът остава за неподменения legacy каталог. Builder записите не изискват
добавяне в manifest, статични преводи, HPWJ номера или brand/model правила.

## Констатации и точни поправки

### BLOCKER

**B1 — мутация на публикувано техническо доказателство през legacy upload route.**
`POST /api/technical-library/{id}/revisions` допускаше Builder-owned
TechnicalDocument, въпреки че Builder graph е заключен. В базовата версия двата
регресионни случая PUBLISHED/RETIRED върнаха `201` вместо `409`. Това позволява
подмяна на runtime PDF bytes/title/hash извън ревизионното публикуване.
Добавен е server-side конфликт `catalog_published_content_immutable` за
`builder_artifact_id != NULL`. Тестовете сравняват всички колони и броя document
revisions преди/след отказа за текуща и retired публикация.

### HIGH

**H1 — V2 Repair Kit в режим KIT за несъвместима машина.** Общият ред няма
`catalog_part_id`, поради което предишната валидация на части се заобикаляше.
Базовият regression върна `201`. Централният `require_compatible_kit` вече
проверява компонентите срещу потвърдената V2 съвместимост; отказът е `409`.
Builder kit проверката продължава да изисква текущото изрично обвързване.

**H2 — конкурентно първоначално обвързване може да промени избора между редове.**
`None` означаваше едновременно „няма captured binding“ и „изборът още не е
изчислен“. Проверка на следващ ред можеше отново да избере каталог след
конкурентен bind. Въведен е отделен sentinel за неизчислен избор; captured `None`
се спазва за цялата заявка. PostgreSQL request selection взема shared Machine
lock, след това shared CatalogDefinition lock, в същия ред като bind. Нов реален
PostgreSQL тест проверява отказ с SQLSTATE `55P03` за конкурентен bind и успех
след освобождаване на транзакцията. Това е намерен чрез преглед race; не се
твърди, че е наблюдаван продукционен инцидент.

### MEDIUM

**M1 — позволени имена произвеждат caption 513 символа в колонa VARCHAR(500).**
Две authoring стойности по 255 плюс ` — ` водят до PostgreSQL publication failure.
`CatalogDiagram.title` е Text. Нова additive миграция `20260930_0030` с parent
`20260929_0029` разширява колоната. Downgrade проверява наличните стойности и
отказва преди промяна при дължина над 500. SQLite и PostgreSQL тестове проверяват
запазване, максимална стойност и безопасния отказ. Старите миграции не са редактирани.

**M2 — alternative part number липсва от търсенето.** Добавен е в server-side
search. Runtime DTO и локалният UI search вече съдържат alternative number,
supplier/supplier code, assembly и съществуващите езикови имена.

**M3 — руският Builder part name се губи в runtime.** DTO вече връща
`description_ru`; Builder имената и cart редовете използват избрания BG/EN/RU
език с canonical fallback. Историческото V2 EN/BG представяне се запазва.
Нови unit/API тестове проверяват трите Builder имена и legacy поведението.

**M4 — multi-touch/pointercancel оставя случайна геометрия.** Hotspot editor
следи touch pointers, отменя започнатото редактиране при втори пръст, възстановява
предишния draft при cancel и блокира ново рисуване до края на жеста. Не приема
неосновен mouse button. Regression покрива pinch/cancel и нормално рисуване/save.

**M5 — Builder runtime ненужно влиза във V2 manifest.** `machine_family()` е
преместен след Builder return. API тестът подменя legacy manifest loader с
изключение и изисква работещ Builder runtime/search.

**M6 — importer защита на Builder documents зависи от налични bytes/path.**
При липсващи bytes старият importer можеше да архивира Builder document.
Document и останалите V2 upsert/archival queries вече изрично изключват Builder
lineage. QA corruption тестът доказва, че V2 importer не променя такъв document.
Това не ремонтира липсващи bytes и не ги признава за валидно доказателство.

### LOW

Няма отделни установени LOW дефекти, изискващи промяна.

### OBSERVATIONS

- Продължителните локални Docker/pytest опити срещат тежко забавяне на файловата
  система/паметта. Част от ранните опити са прекъснати; те не са PASS.
- Compose production rehearsal има изрична CI-only защита. Тя не е заобикаляна.
  За този gate е необходим действителният repository CI резултат.
- Frontend build преминава с advisory за голям bundle chunk; това не е build error.
- Няма промени по MFA/SSO, лицензиране, signature/security roadmap или други
  несвързани продуктови функции.

## Заключения по интегрираните договори

| Област | Прегледан договор и доказателство |
|---|---|
| Архитектура | Един shared operational runtime, request service и document renderer; generic AssetCategory и explicit binding. |
| Един каталог / много машини | Нов acceptance test публикува преди създаването на A/B; B е unsupported до bind, после получава същата публикация без republish и без промяна на PartCatalog/compatibility списъци. |
| Една машина / един каталог | UNIQUE machine binding плюс Machine lock в bind; съществуващ PostgreSQL competing bind test. |
| Category/capabilities | Binding/readiness изискват активна подходяща категория; generic asset/category тестове проверяват capabilities. |
| Draft visibility | Live материализация само при publish; runtime selects текущ PUBLISHED scope. Съществуващите Builder/publication tests проверяват изолация. |
| Current publication | Partial unique index за PUBLISHED/catalog; publish сравнява expected current и digest под catalog/revision locks. |
| Digest | Canonical JSON включва catalog metadata, revision identity, assemblies, PDF SHA/page metadata, roles, all semantic part fields/maps, hotspot geometry/version/verification, kits/components. Bytes се валидират срещу SHA при readiness. |
| Atomic publication | Една транзакция за live graph, retirement, status и audit. Съществуващ forced failure test плюс нов PostgreSQL replacement-failure test изискват пълен rollback и старата PUBLISHED ревизия. |
| Publication races | Съществуващи реални PostgreSQL competing publish, part-edit и request/publish tests; добавени hotspot/kit edit races. |
| Lineage | Изрични builder FK за всички материализирани структури; retirement запазва старите rows. |
| Immutability | Draft guards в authoring; live part/hotspot guards; B1 затваря legacy technical-document escape. GeneratedDocument/snapshot bytes не се пренаписват от publish/seed/import. |
| Clone | Копира целия graph с нови IDs/remapped FK, оригинални PDF bytes/SHA/roles, part/source maps, verification evidence и kit components; code_locked е запазен и след component removal. |
| Hotspot verification | Geometry/version change изисква повторна проверка; exact occurrence/position позволява варианти и повторени occurrence-и без автоматично OCR потвърждение. |
| Position 80 | Съществуващ 0029 разширява всички relevant position columns; API/request/snapshot/DOCX acceptance проверява 80 символа; downgrade не реже данни. |
| Repair Kits | Generic assembly/revision scope, задължителни/optional components и quantities; KIT/COMPONENTS използват shared request validation; H1 затваря legacy KIT bypass. |
| Runtime/IDOR | Machine binding + current revision scope за parts, kits, assemblies, diagram/hotspot/page/source bytes. Нов foreign-catalog тест използва две публикувани каталожни области от една категория. |
| Generic /api/catalog | Legacy route също избира Builder revision при machine context; не връща чужд Builder/V2 mix. |
| Static boundaries | Builder serialization/search не използват статични V2 translations; M5 премахва излишния manifest call от machine runtime. |
| PARTS-DOC | Shared request snapshots, approved language template, final-byte hash registration и 4 колони Поз./PART №/Описание/Количество. Нов E2E генерира DOCX/PDF за A/B. |
| Separate PDFs | Explicit role + artifact SHA + page; няма filename/page/diagram title inference. Съществуващ separate-PDF regression сравнява scheme/list SHA независимо. |
| Multiple/grouped pages | Group key пази source/revision/hash/role/page. Нов regression проверява две точни list pages, два variants и две occurrences; един scheme appendix с две contributions. |
| Historical requests | Snapshots и всички GeneratedDocument колони се сравняват преди/след repeated seed/import и clone/edit/publish B. Retirement не изтрива доказателствата. |
| Failure safety | Existing snapshot/render failure tests проверяват transaction rollback; не се връща частичен официален документ като успешен. |
| Owner deletion | Owner-only safe preview/confirmation; non-DRAFT revision блокира CatalogDefinition delete; explicit subtree и FK dependencies пазят operational history. Съществуващи deletion/concurrency tests. |
| Unbind/reassign | Published bindings са защитени; не се допуска произволно преместване на machine към друг текущ каталог. |
| Authorization/errors | Central permission inventory класифицира всички Builder routes; structured conflicts и безопасни source validation errors. Няма secret/password output добавен от поправките. |
| Seed/import | Изрична V2 ownership граница, повторен seed/import в acceptance и legacy anchors; M6 премахва path/bytes heuristic за Builder ownership. |
| Migration/DB | Една Alembic верига до 0030; protected historical SHA запазени; FK/unique/check constraints, runtime indexes и lengths прегледани. Upgrade/backup rehearsal още се изпълнява. |
| Backup/restore | Supported encrypted backup/verify/restore и PostgreSQL migration rehearsal са задължителни; Builder-specific round trip трябва да сравни graph, hashes, bindings и исторически request documents. Резултатът още не е PASS. |
| Frontend/mobile | Builder workflow и runtime използват i18n; 534 frontend tests PASS, включително runtime names и hotspot gesture regressions. Физически touch-device тест не е изпълнен. |
| CI gates | Full backend test discovery включва новите regressions; реалните PostgreSQL случаи са в отделния CI job; Docker/LO/Compose/backup gates са налични. |

## Команди и действителни резултати

Съдържанието на командите е дадено относително към изолирания audit checkout;
не се публикуват локални вътрешни host paths, секрети или database credentials.

| Команда | Резултат към този checkpoint |
|---|---|
| `python backend/scripts/validate_migration_history.py --require-all-protected` | PASS; 30 protected migrations, без missing/mismatched/unprotected. |
| `PYTHONPATH=backend python backend/scripts/catalog_v2_validation.py` | PASS; 9/9 authoritative source fingerprints unchanged. |
| `PYTHONPATH=backend python backend/scripts/build_catalog_translations.py --check` | PASS. |
| `python backend/scripts/validate_authorization_inventory.py` | PASS; 231 routes, 116 mutations, без inventory errors. |
| `python -m ruff check backend scripts tests` | PASS; ще се повтори след последните test edits. |
| `python -m compileall -q backend scripts tests` | PASS. |
| `python -m pip check` | PASS. |
| `python -m pytest --collect-only -q -m 'not postgres'` | 1034 backend tests collected, 56 PostgreSQL cases deselected преди добавянето на replacement rollback case. |
| `python -m pytest -q -m 'not postgres' -o tmp_path_retention_policy=failed -o tmp_path_retention_count=1 --durations=10 --junitxml=…` | В процес в Windows и disposable Linux QA; няма финален PASS. |
| `python -m pytest -q tests/postgres -o tmp_path_retention_policy=failed -o tmp_path_retention_count=1 --durations=10 --junitxml=…` | В процес на реален PostgreSQL 16; няма финален PASS. |
| `python -m pytest -q tests/test_catalog_final_audit.py tests/test_catalog_title_migration.py --junitxml=…` | Final focused run в процес; ранният subset след initial fixes има 5 PASS, но не покрива последните добавени сценарии. |
| `pnpm typecheck` | PASS. |
| `pnpm lint` | PASS. |
| `pnpm test --maxWorkers=2 --reporter=default --reporter=junit --outputFile.junit=…` | PASS; 534 tests / 52 files, 116.17 s. Ограничени workers, пълен suite. |
| `pnpm build` | PASS; advisory за bundle chunk size. |
| `docker build --load --build-arg ASSETCORE_RELEASE_SHA=b5515081025042a557f1ae54dc4433681ed6ad44 --tag assetcore:final-catalog-audit .` | Build/export още се проверява; QA image е построен, но не замества final production-image gate. |
| `python backend/scripts/container_runtime_smoke.py` | Final image run остава. |
| `python backend/scripts/part_visual_appendix_smoke.py` | Final LibreOffice PARTS-DOC QA остава. |
| `python scripts/verify_release.py --output …` | Ранен опит отказа поради липсващи CI dependency pins в QA средата; повторение остава. |
| `python scripts/postgres_smoke_test.py` | Ранен опит timeout при migration subprocess в бавната QA среда; повторение остава. |
| `python scripts/production_compose_smoke.py --sha …` | Не се заобикаля CI-only guard; чака действителен CI резултат. |
| `git diff --check` | PASS. |

Ранният negative regression run върху базата има **4 failures / 1 pass**:
двата B1 случая, M2 и H1 са възпроизведени преди поправките. Ранен пълен
frontend run срещна две timing failures в несвързан MachineEntryActions test
при натоварване; пълното повторение с два workers има всички 534 PASS.

## Проверени legacy anchors

V2 authoritative validator запазва **611 части**, **7 Repair Kits**,
**84 RepairKitComponents**, **12 exploded diagrams**, **818 verified hotspots**
и **19 проверени HPWJ машини**. Builder QA records се броят отделно, никога
като authoritative inventory. Статичните BG/EN каталожни преводи покриват 611
canonical source identities. Не са променени source datasets/регистри,
seed inventory или binary reference документи.

## Какво точно остава

1. Финални пълни backend и реални PostgreSQL резултати за fix HEAD, включително
   всички нови acceptance/race/length/rollback cases.
2. Финален production Docker build и non-root, readiness, LibreOffice PARTS-DOC QA.
3. Pre-Builder upgrade preservation и encrypted Builder backup/verify/restore
   с comparison на bindings, graph, snapshots и issued document hashes.
4. Actual CI-only Compose init/restart/verified-backup upgrade gate.
5. Проверка на окончателния diff за verified materials и последващ независим PR review.

До приключване и документиране на тези точки: **NOT READY FOR PRODUCTION**.
Deployment изисква отделна изрична задача след review; този одит не го разрешава.
