# Catalog Builder: извличане от няколко физически страници

PR: https://github.com/djebedaq/AssetCore/pull/98 — отворен draft, без merge/deploy.

База: `fd89684ee348bd3724af8ff6dbeb01eaec5ead96` (`origin/main` при започване).
Последен implementation commit: `1bacd5d5362d1fb9f235fa5c01e896418e5616cc`.
Финалният HEAD включва този код и QA доказателствата; точният SHA е в PR и крайния отчет.

## Причина и възпроизвеждане

Frontend вече изпраща заявка за всеки изрично зададен `SPARE_PARTS_LIST`.
Backend връща източниците по `sort_order`, а `visual_page_id` избира точния
reference-local artifact alias и физическа PDF страница. SHA идентичността на
споделените blobs не е причината за загубата.

Разпознатата таблица с линии обаче заобикаля `layout_rows`, където е съществувал
механизмът за продължение. `ruled_rows` не получава continuation контекста и
приема първия физически ред за заглавие. За таблица без повторено заглавие така
се губи първата част, а останалите редове остават с неразрешена схема.
Таблиците с линии не са запазвали нормализирани граници за следващата страница.

Детерминираното възпроизвеждане върху базовия код дава:

| Физическа страница | Части | Запазени редове за mapping | Първа запазена позиция |
|---|---:|---:|---:|
| 2: заглавие + позиции 1–5 | 5 | 5 | 1 |
| 3: без заглавие, позиции 6–10 | 0 | 4 | 7 |

Втора причина за непълни резултати: общият `try/catch` във frontend прекъсва
целия цикъл при отказ на една заявка. Успешните previews остават, но следващите
източници не се обработват. Нямало е обобщен отчет, който да отчита всяка
зададена страница и частичния отказ.

Production базата и първоначалната acceptance сесия не са отваряни. Причините
са доказани върху runtime synthetic QA PDF и реалния интерфейс, без измислени
производствени записи или промени в оригинални документи.

## Поведение след корекцията

- Едно действие обхожда всички зададени списъци в явния `sort_order`; схемите
  не участват в извличането. Няма специален лимит от две страници.
- Всеки preview запазва собствен signed token и точен физически източник.
  Един общ преглед и бутон за потвърждение обработват отделните previews.
- Продължение се предава само при еднакъв SHA и съседни физически страници.
  Повторено или самостоятелно заглавие се разпознава по текущата страница.
  Различни PDF документи не получават чужда схема.
- Таблиците с линии запазват нормализирани граници, заглавия и разрешена схема.
  Headerless продължение използва точно една съвместима геометрия и валидни
  позиции. Редовете получават `CONTINUATION_INFERRED` и изискват човешки преглед.
- Несъвместимо/неясно продължение запазва всички клетки, включително първата
  част, като `NEEDS_REVIEW` с `CONTINUATION_UNRESOLVED`. Mapping е само за тази
  физическа страница. Успешните previews, редакции и потвърдени редове се пазят.
- Нулев резултат е видим като нуждаещ се от внимание с конкретен PDF и номер.
  OCR disabled/unavailable/pixel-limit и table-detection предупреждения са
  видими. При липса на разпознаваема таблица остава съществуващото ръчно въвеждане.
- Отказ на един източник не спира следващите. Бутонът за повторен опит е само
  за отказалия източник; след отказ continuation веригата се прекъсва.
- Обобщението показва общ брой, обработени/зададени източници, брой и статус
  за всяка страница. BG/EN/RU ключовете са с пълен паритет.
- Confirmation запазва artifact ID, SHA, PDF номер, `visual_page_id`, точни
  row cells/raw text/bbox и extractor evidence. Тестовете проверяват отделните
  page maps. `extraction_key` и защитата на човешките редакции не са променени;
  повторното потвърждение създава нула дубликати. Няма глобална дедупликация.

## Проверки

| Проверка | Точно изпълнена команда / обхват | Резултат |
|---|---|---|
| Нови backend регресии | `.venv/Scripts/python.exe -m pytest -q tests/test_catalog_multipage_extraction.py --tb=short` | 10 passed |
| Catalog + PARTS-DOC | `.venv/Scripts/python.exe -m pytest -q tests/test_catalog_guided_builder.py tests/test_catalog_multipage_extraction.py tests/test_catalog_selected_extraction.py tests/test_catalog_extraction_schema.py tests/test_catalog_extraction_columns.py tests/test_catalog_extraction_boundaries.py --tb=short` | 82 passed |
| Full frontend | `pnpm --dir frontend exec vitest run --maxWorkers=2` | 56 files, 558 passed |
| Typecheck | `pnpm --dir frontend run typecheck` | PASS |
| Frontend lint | `pnpm --dir frontend run lint` | PASS |
| Build | `pnpm --dir frontend run build` | PASS; съществуващ size warning за chunk над 500 kB |
| Python lint | `.venv/Scripts/python.exe -m ruff check backend/app backend/alembic backend/scripts scripts tests` | PASS |
| Release | `.venv/Scripts/python.exe scripts/verify_release.py --output .tmp/multipage-release` с изолирана DB настройка | 26/26 PASS |
| Full backend | PR CI, `python -m pytest -q -m "not postgres" --durations=10` | 1125 passed, 3 skipped, 64 deselected |
| PostgreSQL | PR CI PostgreSQL 16, `python -m pytest -q tests/postgres --durations=10 --junitxml=postgres-test-results.xml` | 64 passed (включително 3 нови multi-page случая) |

Двустраничните тестове проверяват позиции 1–10 и точно 10 потвърдени части под
една logical Reference Page. Headerless тестовете покриват таблици с линии и
без линии. Случаите с три страници проверяват позиции 1–15 и 15 части. Допълнително
се проверяват отделни PDF документи, явен source reorder и несъвместим layout.

PARTS-DOC е проверен чрез съществуващия
`test_repeated_position_multi_scheme_extraction_publication_two_machines_and_parts_doc`:
публикация, две машини, локални варианти/повторени позиции, точни visual snapshots,
генерирани документи и неизменна историческа документация.

Браузърният тест `tests/browser/catalog_multipage_extraction.mjs` е изпълнен в
реалния Catalog Builder с отделен QA сървър, runtime synthetic PDF и временна
SQLite база. Схемата и двата списъка са зададени чрез UI; Extract е натиснат
веднъж, позиции 1–10 са видими и след човешки преглед са потвърдени 10 части.
И трите сценария минават: повторени заглавия, headerless продължение и mapping
само на втората страница. `browser-proof.json` и двата PNG файла пазят резултатите.

Първите едновременно пуснати frontend набори имат таймаути; ограниченото
изпълнение с два workers минава изцяло. QA образът няма pytest-xdist и първият
опит с `-n` е невалиден. Локалната Docker проверка е преместена във временна
памет след бавни дискови записи. Неуспешните/прекъснати опити не се броят за PASS.
Локалният PostgreSQL опит е прекъснат след два failure markers, без завършен
диагностичен отчет. Той не се отчита за успешен; независимият пълен CI run
по-долу завършва с 64 passed. Финалната проверка на Catalog/PARTS-DOC след
уточняването на schema evidence също завършва с 82 passed.
Пълният PostgreSQL резултат за финалния implementation commit е от [CI job](https://github.com/djebedaq/AssetCore/actions/runs/37456033326/job/112243755970).
Пълният backend резултат за финалния implementation commit е от [CI job](https://github.com/djebedaq/AssetCore/actions/runs/37456033326/job/112243755766).
Локалният backend run също е прекъснат след независимото успешно CI изпълнение;
той не е отчетен като успешен пълен набор.
Трите пропуснати backend проверки са две original-protocol layout проверки
без LibreOffice в backend job и една проверка за Windows named mutex на Linux.
Docker CI job също минава: изолирани encrypted backup/restore проверки,
offline OCR, официален visual appendix и Builder document renderer.

CI frontend job спира преди тестовете върху непроменени зависимости:
`source-map-js@1.2.1` (HIGH, `GHSA-68fv-2mgg-jv7q`) и `tinypool@1.1.1`
(CRITICAL, `GHSA-5gmw-xhrv-c9v3` / `GHSA-85c8-ppgw-ccpr`).
Няма промяна в `package.json` или `pnpm-lock.yaml`. Това ограничение е извън
фокусирания bugfix; PR остава draft, без заобикаляне на security gate.

## Променени файлове и граници

Backend: `parts_extraction/extraction.py`, `process.py`, `tables.py`, `service.py`.
Frontend: `GuidedParts.tsx`, `guidedTypes.ts`, `guidedTranslations.ts`, `GuidedParts.test.tsx`.
Тестове: `test_catalog_multipage_extraction.py`,
`postgres/test_catalog_multipage_extraction_postgres.py`,
`browser/catalog_multipage_extraction.mjs`.
QA: този отчет, `browser-proof.json`, `continuation-review.png`, `mapping-review.png`.

Production е недокоснат. Няма deployment, production migrations, merge,
cloud OCR, външен AI, schema migration или промяна на друга Builder функционалност.
Финалният diff не променя проверения 19-machine HPWJ seed, source registers,
оригинални DOCX/PDF или съществуваща audit/document/transfer/repair история.
