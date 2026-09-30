# FINAL-CATALOG-AUDIT-01 — Catalog Builder 01A–01E

Авторитетна база: `b5515081025042a557f1ae54dc4433681ed6ad44`.
Работен клон: `assetcore-final-catalog-audit`, създаден от тази точна база.
Дата на одита: 30.09.2026 г.

**Статус: NOT READY FOR PRODUCTION.** Необходимите поправки са завършени в
[PR #94](https://github.com/djebedaq/AssetCore/pull/94). Проверяван code HEAD:
`d2d33baf1fed21d27039f30a0b37078cf785e4c9`.
[CI run 272](https://github.com/djebedaq/AssetCore/actions/runs/36701151891)
е авторитетното изпълнение за този HEAD. Финалното обновяване на този доклад не
променя code, tests, migrations или workflow спрямо проверявания HEAD.
Всички четири jobs в този run са SUCCESS, приключили до 10:33:47 UTC.
Остава последващ независим review на fix PR съгласно т. 78 от задачата;
този одит не разрешава deployment. Няма останал известен непоправен
BLOCKER/HIGH/MEDIUM в проверения scope.

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

| Слой | Действителни repository модули / regression evidence |
|---|---|
| Control plane | `backend/app/catalog_admin/{routes,schemas,service,repository,parts,visual_sources,hotspots,repair_kits}.py`; `backend/app/models.py`; `tests/test_catalog_builder*.py`. |
| Readiness/publish/clone | `backend/app/catalog_admin/publication.py`, `service.py`; `tests/test_catalog_publication.py`; `tests/postgres/test_catalog_publication_postgres.py`, `test_catalog_builder*_postgres.py`. |
| Binding/runtime/compatibility | `backend/app/catalog/{runtime_context,service,repository,schemas}.py`; shared request/repair integration; `tests/test_catalog_final_audit.py`, `tests/postgres/test_catalog_final_audit_postgres.py`. |
| Evidence/PARTS-DOC | `backend/app/part_requests/visual_snapshots.py`, `backend/app/visual_snapshot_schema.py`; shared official renderer/registry; `tests/test_part_visual_snapshots.py`, `tests/test_part_request_visual_appendix.py`, PostgreSQL counterparts и двата visual smoke scripts. |
| Legacy sources/seed | `backend/app/catalog/{importer,validation,position_mapping}.py`; `docs/SOURCE_REGISTER_BG.md`; authoritative manifest/datasets и protected seed inventory, без редакции. |
| UI | `frontend/src/features/catalogBuilder/`, `frontend/src/features/catalog/`; component/i18n tests в пълния frontend suite. |
| Upgrade/backup/deployment QA | `backend/alembic/`, protected migration manifest; `scripts/postgres_smoke_test.py`, `tests/postgres/catalog_builder_backup_rehearsal.py`, `scripts/production_compose_smoke.py`, `.github/workflows/check.yml`. |

При runtime обвързването и текущата PUBLISHED ревизия са авторитетни. V2
manifest-ът остава за неподменения legacy каталог. Builder записите не изискват
добавяне в manifest, статични преводи, HPWJ номера или brand/model правила.
Преди първа Builder публикация draft-only binding не отнема допустимия legacy
V2 fallback; generic неподдържана машина остава unsupported. Това следва
изричното изискване в т. 8, без да прави draft graph runtime съдържание.

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

**L1 — frontend assertions преди приключване на effects.** Machines URL cleanup
и QR fetch assertions четяха състоянието веднага след появяване на placeholder
UI. В един CI run се провалиха 2/534 теста; добавен е `waitFor` за самото
очаквано действие. Проверяваните резултати и permissions не са променени.

**L2 — suite-order dependency в repair logging тест.** След runtime тестове
Uvicorn parent logger не propagate-ва към root, където `caplog` слуша. API
правилно връщаше diagnostic ID и rollback, но тестът не намираше emitted record.
Capture handler вече е закачен към самия service logger за този тест и се
възстановява с monkeypatch. Няма промяна в production logging/repair behavior.

### OBSERVATIONS

- Продължителните локални Docker/pytest опити срещат тежко забавяне на файловата
  система/паметта. Част от ранните опити са прекъснати; те не са PASS.
- Compose production rehearsal има изрична CI-only защита. Тя не е заобикаляна.
  Gate-ът премина в действителния repository CI, включително init/refuse-existing,
  same-image restart без prepare и stop/backup/verify/prepare/ready/shell.
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
| Multiple/grouped pages | Group key е explicit role + immutable artifact SHA + page. Всяка contribution пази captured source/revision lineage. Нов regression проверява две точни list pages, два variants и две occurrences; един scheme appendix с четири contributions (две части × две occurrences), с markers 1/2. |
| Historical requests | Snapshots и всички GeneratedDocument колони се сравняват преди/след repeated seed/import и clone/edit/publish B. Retirement не изтрива доказателствата. |
| Failure safety | Existing snapshot/render failure tests проверяват transaction rollback; не се връща частичен официален документ като успешен. |
| Owner deletion | Owner-only safe preview/confirmation; non-DRAFT revision блокира CatalogDefinition delete; explicit subtree и FK dependencies пазят operational history. Съществуващи deletion/concurrency tests. |
| Unbind/reassign | Published bindings са защитени; не се допуска произволно преместване на machine към друг текущ каталог. |
| Authorization/errors | Central permission inventory класифицира всички Builder routes; structured conflicts и безопасни source validation errors. Няма secret/password output добавен от поправките. |
| Seed/import | Изрична V2 ownership граница, повторен seed/import в acceptance и legacy anchors; M6 премахва path/bytes heuristic за Builder ownership. |
| Migration/DB | Една Alembic верига до 0030; protected historical SHA запазени; FK/unique/check constraints, runtime indexes и lengths прегледани. Pre-0025 upgrade и данните във всички предходни колони са сравнявани чрез counts/SHA. PASS в CI. |
| Backup/restore | PASS: supported encrypted backup/verify/restore, PostgreSQL 16 toolchain и PG17 rejection; Builder-specific round trip сравнява всички таблици/колони, bindings, graph, snapshots и request documents. Предходните audit rows са exact; нов restore event е допустим. |
| Frontend/mobile | Builder workflow и runtime използват i18n; 534 frontend tests PASS в CI, включително runtime names и hotspot gesture regressions. Физически touch-device тест не е изпълнен. |
| CI gates | Full backend test discovery включва новите regressions; реалните PostgreSQL случаи са в отделния CI job; Docker/LO/Compose/backup gates са налични. |

## Команди и действителни резултати

Съдържанието на командите е дадено относително към изолирания audit checkout;
не се публикуват локални вътрешни host paths, секрети или database credentials.

| Команда | Финален действителен резултат |
|---|---|
| `python backend/scripts/validate_migration_history.py --require-all-protected` | PASS; 30 protected migrations, без missing/mismatched/unprotected. |
| `PYTHONPATH=backend python backend/scripts/catalog_v2_validation.py` | PASS; 9/9 authoritative source fingerprints unchanged; position mapping/provenance/geometry: 581 mapped positions, 818 occurrences, 0 unresolved, 2 source-confirmed not drawn. |
| `PYTHONPATH=backend python backend/scripts/build_catalog_translations.py --check` | PASS. |
| `python backend/scripts/validate_authorization_inventory.py` | PASS; 231 routes, 116 mutations, без inventory errors. |
| `python -m ruff check backend scripts tests` | PASS след последните code/test edits; също PASS в CI. |
| `python -m compileall -q backend scripts tests` | PASS. |
| `python -m pip check` | PASS. |
| `python -m pytest --collect-only -q -m 'not postgres'` | 1034 backend tests selected, 56 PostgreSQL cases deselected; final discovery е 1090 случая. |
| `python -m pytest -q -m "not postgres" --durations=10` | PASS в CI: 1031 passed, 3 skipped, 56 deselected, 225 warnings, 1112.55 s. Локалните пълни Windows/Linux опити са прекъснати и не се броят за PASS. |
| `python -m pytest -q tests/postgres --durations=10 --junitxml=postgres-test-results.xml` | PASS: 56/56 на реален PostgreSQL 16 в CI, 313.21 s. Локалният частичен опит е прекъснат. |
| `python -m pytest -q tests/test_runtime_deployment_hardening.py` | PASS в CI: 17 tests, 6.74 s. |
| `python -m pytest -q tests/test_catalog_final_audit.py tests/test_catalog_publication.py tests/test_final_release_infrastructure.py -o tmp_path_retention_policy=all --junitxml=audit-evidence/catalog-focused-final.xml` | PASS: 19/19, 66.40 s в SQLite/Windows. |
| `python -m pytest -q tests/test_runtime_deployment_hardening.py tests/test_internal_repair_protocol_v11.py tests/test_final_release_infrastructure.py` | PASS: 30/30, 45.37 s; включва repair logger order regression. |
| `pnpm typecheck` | PASS. |
| `pnpm lint` | PASS. |
| `pnpm test` | PASS в CI: 534 tests / 52 files, 30.50 s. Локален предходен пълен run с два workers: 534 PASS, 116.17 s. Последващ локален run имаше две timing failures в MachineEntryActions; те не се скриват и не заместват успешния CI run. |
| `pnpm build` | PASS; advisory за bundle chunk size. |
| `docker build --pull --build-arg ASSETCORE_RELEASE_SHA=$GITHUB_SHA --tag assetcore:ci --tag assetcore:$GITHUB_SHA .` | PASS в repository CI за test merge ref на code HEAD. Локалният build/export е прекъснат; не се брои за финален PASS. |
| `docker run --rm --read-only --network none --tmpfs /tmp:rw,nosuid,noexec,size=512m assetcore:ci python backend/scripts/container_runtime_smoke.py` | PASS: fixed non-root runtime и реален DOCX→PDF. |
| `docker run --rm --read-only --network none --tmpfs /tmp:rw,nosuid,noexec,size=512m assetcore:ci python backend/scripts/part_visual_appendix_smoke.py` | PASS: V2 PARTS-DOC final hashes, grouped pages/images и actual LibreOffice PDF. |
| `docker run --rm --read-only --network none --tmpfs /tmp:rw,nosuid,noexec,size=512m assetcore:ci python backend/scripts/catalog_builder_document_smoke.py` | PASS: две късно обвързани Builder машини, 80 символа в DOCX/PDF, exact scheme/list pages и real conversion без fallback. Повторено локално; трите страници за A са визуално прегледани, B има същата структура и отделна asset identity. |
| `python scripts/verify_release.py --output release-verification` | PASS в CI: protected migrations/head, exact inventory/roles, source/translations, 12 approved BG/EN/RU templates, document QA, dependency manifests/SBOM, health и integrity guard. Ранният локален опит с липсващи CI pins не е PASS. |
| `python scripts/audit_dependencies.py python --output security-reports/python-audit.json` | PASS в CI; high/critical/unknown gate. |
| `python3 scripts/audit_dependencies.py frontend --output security-reports/frontend-audit.json` | PASS в CI; high/critical/unknown gate. |
| `python scripts/postgres_smoke_test.py` | PASS в CI: migration/head, encrypted backup/verify/restore; в exact production image също PASS с real PG17 mismatch rejection. Ранният локален timeout е средов failure. |
| `python tests/postgres/catalog_builder_backup_rehearsal.py` | PASS в CI: pre-0025 → 0030 preservation, A/B graph, late bindings, immutable documents/snapshots и authenticated encrypted restore. |
| `python scripts/production_compose_smoke.py --sha "$GITHUB_SHA"` | PASS в CI. Изричната CI-only защита е спазена. |
| `git diff --check` | PASS. |

Ранният negative regression run върху базата има **4 failures / 1 pass**:
двата B1 случая, M2 и H1 са възпроизведени преди поправките. Ранните CI failures
на новата occurrence expectation (2 вместо правилните 4 contributions), стария
logging test и frontend async assertions са поправени; финалният run е green.
Трите full-backend skips са условни platform/tool случаи: Windows named mutex
на Linux и двата transfer-signature layout случая без LibreOffice в backend job.
Actual LibreOffice QA е изпълнена успешно в production Docker image job;
не се твърди, че skipped transfer-signature tests са изпълнени.

## Проверени legacy anchors

V2 authoritative validator запазва **611 части**, **7 Repair Kits**,
**84 RepairKitComponents**, **12 exploded diagrams**, **818 verified hotspots**
и **19 проверени HPWJ машини**. Builder QA records се броят отделно, никога
като authoritative inventory. Статичните BG/EN каталожни преводи покриват 611
canonical source identities. Не са променени source datasets/регистри,
seed inventory или binary reference документи.

## Какво точно остава

1. Последващ независим review на единствения fix PR #94 и неговите поправки.

Всички изисквани приложими автоматизирани gates са успешни; финалният diff е
проверен за seed data, source registers, historical migrations и binary
reference documents — няма промени по тях. Новата миграция и manifest entry
са additive. QA logs, бази и генерирани документи не са committed.
Остават ограничения на доказателството: няма изпълнение върху физическо touch
устройство; локалните натоварени runs са нестабилни/прекъсвани, както е описано
по-горе; production е извън scope и не е тествана или достъпвана.

До независимия review: **NOT READY FOR PRODUCTION**.
Deployment изисква отделна изрична задача след review; този одит не го разрешава.
