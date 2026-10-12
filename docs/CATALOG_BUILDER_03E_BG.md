# Catalog Builder 03E — OEM layout extraction

## Обхват и база

Начална база: `origin/main` = `1bdb74b1c6d78d99ac4072690b66b5bf7b8d6be0` (03A–03C). Клон: `feature/catalog-builder-03e-oem-layout-extraction`. Диагностичен източник: Draft [PR #104](https://github.com/djebedaq/AssetCore/pull/104), `0dec19a37ac08ed78f938400503207dd76d97dc5`. Неговият HEAD, draft статус и петте поправки не са променяни. Не е копиран целият 03D diff.

03E възстановява 611/611 контролни записа от осем разрешени оригинала чрез native текст и локална геометрия. D13 остава 20/20 + 10/10 при три Linux повторения. Това е точност на извличане, **не** автоматично човешко одобрение или готовност за публикуване.

Няма промени в DB схема, миграции, permissions, роли, OCR зависимости, ресурсни лимити, inventory, Falch номерация, controls, source register, оригинални документи, published revisions или historic artifacts. Няма нов workflow или UI redesign.

## Независима диагностика на 24 физически страници

За всяка страница са проверени native думите, PDF векторните линии, резултатът на `find_tables()`, разположението на клетките и източникът. Геометричните диагностични изображения съдържат само рамки/линии; оригиналните текстове, клетки и PDF рендери остават извън Git. Подробните агрегати са в [geometry-audit.json](qa/catalog-builder-03e/geometry-audit.json).

**23 Falch страници:** качествен native текст; един BOM с десет физически колони. `find_tables()` открива горния служебен блок, а не BOM. Таблицата е начертана като повтарящи се хоризонтални ръбове на отделните клетки, без затварящи вертикални линии. Заглавията са на три реда, на DE/EN/FR. Има отделни езикови описания и допълнителни колони за замяна/приложимост/комплект. Старият line-based анализ избира отделен езиков header ред, слива колоните и поставя описание в quantity. Няма основание за тежък OCR.

**HYDWIN Fussen, стр. 22:** native текст, без raster изображение; истинска затворена таблица с два независими панела по пет колони. Всеки панел има собствена позиция, описание, спецификация, номер и количество. Глобалното еднократно schema mapping не може да разреши повторените роли. Разделянето по локални семантични групи възстановява 29 + 29 физически записи.

Проверени страници по каталог:

| Каталог | Физически страници | Контроли | 03C кандидати / точни | 03E точни / кандидати |
|---|---|---:|---:|---:|
| Falch 1000 drive pump | 2, 3 | 34 | 0 / 0 | 34 / 34 |
| Falch 1000 liquid part | 2, 3 | 46 | 0 / 0 | 46 / 46 |
| Falch 1000 wheel jet | 4–9 | 164 | 61 / 0 | 164 / 164 |
| Falch 500 pump | 2–4 | 65 | 0 / 0 | 65 / 65 |
| Falch 500 unloader valve | 2–4 | 65 | 33 / 0 | 65 / 65 |
| Falch 500 valve 500bar | 2, 3 | 32 | 0 / 0 | 32 / 32 |
| Falch 500 wheel jet | 4–8 | 147 | 0 / 0 | 147 / 147 |
| HYDWIN Fussen plunger pump | 22 | 58 | 0 / 0 | 58 / 58 |
| **Общо** | **24** | **611** | **94 / 0** | **611 / 611** |

03C сравнението е наследено от независимото измерване на PR #104; 03E не представя това като ново стартиране на 03C. SHA на осемте оригинала и на всичките контролни файлове съвпадат с диагностичната база. Няма мълчаливи поправки в controls.

## Реализация: сегментиране преди семантично възстановяване

1. Съществуващият native table reader остава бързият път за затворени таблици. Независимият word/layout reader продължава да работи и при невалидна таблица от `find_tables()`.
2. Новият `native_grid.py` групира близки хоризонтални векторни ръбове и техните повтарящи се крайни точки. От тях извежда локални колони и физически row bands. Това работи и за отворени клетъчни решетки. Няма OEM координати, номера, бройки или шаблони.
3. Неначертани, действително празни хоризонтални gutters разделят независими таблични острови. Попълнена клетка никога не се изхвърля като gutter. Повторените роли се разделят чрез локално partitioning с проверка за еднозначност; редът и ширината на колоните могат да се различават.
4. `panels.py` изпълнява същия bounded schema scorer за всеки панел. При повече от едно валидно разделяне не се гадае. Силните противоречиви header роли остават двусмислени. `Item`/`No.` не придобиват глобално еднозначно значение.
5. Многоезичните редове в една header клетка се анализират за обща роля. Отделните описателни езикови колони се запазват изцяло в `raw_cells` и `original_descriptions`; първата физическа колона е основното оригинално описание. Не се превежда и не се слива текст от различни езици.
6. Локалните физически граници ограничават края на body областта за word/layout стратегията. Служебният footer не става BOM продължение. Границите не подават стойности или schema на независимия reader.
7. При сравнение локално разрешените физически клетки имат предимство пред текстови редове, които могат да изглеждат по-чисти, защото са изгубили част от пренесена клетка. Конкурентните прочити, предупрежденията и reconciliation изискванията се запазват. Confidence при strategy disagreement се ограничава консервативно.

Ограниченията са явни: до 12 000 хоризонтални сегмента, 24 000 възстановени клетки общо на страница, 80 разглеждани геометрични сигнатури и съществуващите bounded schema/word/result budgets. Превишаването връща review предупреждение и не може да изглежда като пълно извличане. Не са увеличени timeout, memory, pixel или parser-slot настройки.

`SCHEMA_VERSION=2`, `PIPELINE_VERSION=ADAPTIVE_PDF_3`, `EXTRACTOR_VERSION=SPARE_PARTS_3` разграничават новите доказателства. Старите persisted attempts/candidates/decisions не се изтриват. Стар preview capability може да изисква възобновяване от durable session; това не изтрива работа.

## Оригинални стойности, непълни редове и provenance

Всеки панел и ред запазва свои bbox, table/row indices, raw cells, original descriptions, метод и версия. Worker добавя SHA-256 и точната физическа PDF страница. Равни payload-и от различни физически редове получават отделни occurrence keys; не се дедупликират само по номер/позиция.

В редакционния payload се обединяват само визуалните line breaks на description/specification/notes/quantity_raw. Оригиналните клетки и `raw_values` остават непроменени. Неразривни интервали, водещи нули, тирета, точки и подобни символи не се подменят. Няма O/0, I/1 или кирилица/латиница догадки.

Fussen контролите и оригиналът съдържат **три празни Part Numbers и едно ненумерично quantity**. Тези полета се възстановяват точно като празни/нечислови, с `MISSING_PART_NUMBER`/`QUANTITY_UNCERTAIN`; не се измислят идентификатори и числа. Следователно 611/611 exact source records не означава 611 валидни потвърдени части. `quantity_raw` съвпада и за ненумеричния запис, докато numeric quantity остава `null` според оригинала/control.

Контролите се четат единствено от comparator **след** записване на извличането. При Linux извличането контролният directory в image е маскиран с празен read-only tmpfs. D13 expected JSON изобщо не се предоставя на контейнера. Comparator пази multiplicity: всеки контролен запис консумира само един извлечен occurrence. Проверява петте полета, source SHA/page, липсващи и допълнителни редове.

Финалният QA audit поправи и наследен слаб gate в CLI: отрицателно сравнение вече връща exit code 1. Пропуснат/дублиран каталог или физическа страница, сменен SHA и частичен report не могат да се представят като успешен пълен корпус. Седем отрицателни/положителни synthetic comparator теста доказват това; контролите не се променят.

Доказателства: [corpus-summary.json](qa/catalog-builder-03e/corpus-summary.json), [точно сравнение по всички страници](qa/catalog-builder-03e/corpus-linux-comparison.json).

## 03A/03B интеграция и ресурсна безопасност

Използват се съществуващите durable sessions/attempts/candidates, HMAC, inspection receipts, versions, fingerprints и audit. Няма паралелен ledger. Human corrections остават отделни от original evidence. Неясното съответствие при повторно извличане продължава да създава CONFLICT, а не автоматичен вариант. Непроверен, неуспешен или конфликтен източник блокира публикацията.

N-page orchestration и context pass не са пренаписвани. Предават се локална header geometry и semantic mappings; не се копират OEM стойности. Съществуващите регресии покриват 1/2/3/4/7 списъка, по-късен успешен context за по-ранна страница, различни документи и прекъсване/retry.

От петте поправки на PR #104 е избрана само вече проверената **OS parser lease**: `capacity.py`, тясната process интеграция и собствените concurrency/unsafe-storage тестове. Причината е доказаното ограничение на process-local semaphore при повече от един web worker. Файловите OS locks ограничават parser slots в общия runtime namespace; Unix worker наследява descriptor и запазва слота при смърт на web parent. Busy отказът е преди parsing; затварянето освобождава слота. Няма Redis/Celery, нова услуга или увеличение на капацитета.

Останалите четири 03D поправки остават в непроменения Draft #104. 03E не ги замества и не представлява общо release одобрение на 03D.

## Linux Docker, D13 и performance

Използван е production-oriented Docker build, non-root UID 10001, read-only rootfs, network none, 2 CPU, 1 GiB container memory, 64 PID и 192 MiB tmpfs. QA pipeline е bind-mounted read-only върху image; normalized-LF SHA на всеки pipeline модул се записва и е проверен спрямо текущия source. Финалният CI строи image директно от PR HEAD.

Runtime: Python 3.12.15, PyMuPDF 1.26.7, Pillow 12.3.0, Tesseract 5.5.0. Няма нови зависимости. Всички 24 OEM корпусни страници са native; не се стартира OCR за тях. D13 стр. 13 използва съществуващия image/cell OCR, стр. 15 — native fast path.

Трите Linux D13 повторения са отделно сравнени по четирите полета и SHA/page: **3 × (20/20 + 10/10)**. [D13 exact report](qa/catalog-builder-03e/d13-linux-exact.json) съдържа всички измервания и версии. Callout 48 срещу позиция 38 остава нерешен оригинален въпрос. Не са фабрикувани hotspots и D13 не е публикуван.

[Performance report](qa/catalog-builder-03e/performance.json) съдържа median/max за 24 native страници, CPU и sampled process-tree RSS. Това е 20 ms sampling на controller + descendants, не hard peak на целия container. Нова parser процесна граница се стартира за всяка страница. Първото зареждане и filesystem-warm D13 повторенията са разграничени; не се заявява статистически надежден production P95. `queue_wait_seconds=0` в QA adapter не е измерване на опашка: admission е fail-fast. След извличането остават **0 descendants**. Лимитите остават 45 s/1 GiB за worker.

## Тестове и browser QA

Новите synthetic frontend-independent PDF регресии покриват отворени/затворени таблици, DE/EN/FR headers, различен ред на колоните, два/три панела, gutters, wrapped cells, blank PN/quantity, повторени headers, endpoint clustering, cell/segment budget, ambiguous roles, punctuation/неразривни интервали и stable occurrence identity при bbox drift.

Новият normal-API тест доказва отделни candidate IDs за реално отделни synthetic occurrences, CONFLICT при повторена идентичност, запазена човешка поправка след retry, непроверен source и direct publish отказ с актуален digest. Съществуващите 03A/03B/03C assertions не са отслабвани.

Локално изпълнени: Ruff за целия поддържан Python scope, protected migration-history validation, authorization inventory, frontend typecheck/ESLint/production build и extraction/ledger/capacity регресии. Windows-only skips са POSIX process-group, unsafe-storage и inherited-descriptor тестовете; те се изпълняват в Linux CI.

Точни локални резултати: 58 PASS / 7 Windows POSIX skips за layout + adaptive + capacity върху implementation HEAD; допълнително 7/7 comparator теста след QA gate корекцията. Full Vitest: 66 файла, 614 PASS, 246,33 s при един worker. Продуктовият pipeline не е променян след финалните Linux fingerprint/exact измервания.

Реален Edge/D13 browser: една операция извлича 30 кандидата в една таблица, exact values/source 20+10, 390/768/1440 px, keyboard focus, durable edit/refresh, повторно извличане без дубликати, source inspections/decisions и server publication blockers. OEM screenshots остават локални; публикува се само агрегатният [browser report](qa/catalog-builder-03e/browser-d13.json).

Първият browser опит прекъсна при inspection image след source confirmation. Диагностичното повторение след приключване на background PDF заявките върна две HTTP 200 inspection responses и премина всичките седем сценария. Serial QA вече изчаква network idle преди inspection и затваряне на успешно потвърдената attestation форма преди следващия източник. Това не променя продукта и не заменя отделните saturation/concurrency проверки.

Пълните backend/SQLite, PostgreSQL migration/restore/concurrency, frontend/Vitest/translations/security и production Docker/OCR/official document/SBOM проверки се изпълняват от непроменения `Build check`. **Точният финален run URL, HEAD и counts са в PR описанието и checks**, за да се отнасят до финалния commit, а не до саморефериращ документ. Failed/interrupted опитите по разработката не са представени като PASS.

## Възпроизвеждане

```powershell
python -m ruff check backend/app backend/alembic backend/scripts scripts tests
python backend/scripts/validate_migration_history.py --require-all-protected
python backend/scripts/validate_authorization_inventory.py
python -m pytest -q tests/test_catalog_oem_layout_extraction.py tests/test_catalog_adaptive_extraction.py tests/test_catalog_process_capacity.py
python -m pytest -q tests/test_catalog_oem_layout_qa.py
python -m pytest -q -m "not postgres"
python -m pytest -q tests/postgres

# Извличане без expected input; raw report съдържа OEM данни и остава private.
python scripts/catalog_oem_layout_qa.py extract --output .tmp/corpus.json
python scripts/catalog_oem_layout_qa.py compare --report .tmp/corpus.json --output .tmp/corpus-comparison.json
python scripts/catalog_adaptive_pdf_qa.py extract ORIGINAL.pdf --pages 13,15 --runs 3 --output .tmp/d13.json
python scripts/catalog_adaptive_pdf_qa.py compare .tmp/d13.json EXPECTED.json --output .tmp/d13-exact.json
```

За Linux QA същите `extract` команди се изпълняват в image със `--rm --network none --read-only --cpus 2 --memory 1g --memory-swap 1g --pids-limit 64 --tmpfs /tmp:rw,size=192m,mode=1777`. QA scripts и оригиналът са read-only mounts; outputs са отделен QA mount. Контролите са скрити чрез `--tmpfs /app/backend/resources/catalog:ro,size=64k,mode=0555`; `compare` се изпълнява след това на host. Не се използва production Compose, база, secret или volume.

Frontend: `pnpm typecheck`, `pnpm lint`, `pnpm test`, `pnpm build` в `frontend`. Browser: `python tests/browser/run_catalog_simplified_ux_qa.py ORIGINAL.pdf EXPECTED.json` с локалните Playwright/Edge и Tesseract CLI. Wrapper създава нова изолирана SQLite QA база и спира сървъра в `finally`.

## Ограничения и оценка

- PASS за точното автоматично възстановяване на проверените 611 записа и D13 30/30; не е доказана универсална OEM точност.
- Три оригинално празни номера и едно ненумерично количество изискват човешко решение. Strategy disagreements не се скриват. Няма automatic VERIFIED.
- Сложни merged cells, липсващи/нееднозначни граници, непознати headers, силно повредени/наклонени сканове остават safe review/manual path в рамките на старите OCR ограничения. Headerless cross-document schema borrowing остава забранено.
- Hammelmann exact acceptance: **NOT RUN**, няма разрешен оригинал с независим контрол. Други локални HYDWIN оригинали без контрол не са обявени за точни.
- PR #104 остава Draft; останалите му поправки и пълното 03D release приемане са отделна работа за review. 03E не разрешава deployment.

Production не е достъпвана. Не са използвани външни OCR/AI услуги и OEM съдържание не е изпращано навън. Собствените Linux QA контейнери са `--rm`, browser сървърите се спират; оригиналите и локалните QA доказателства са запазени. PR остава неслят за независим review.
