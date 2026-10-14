# CATALOG UX 05 — еднократно потвърждение и публикация с предупреждения

Дата: 14.10.2026. База: `origin/main` — `8303ee2de0b6652748b5178a154b23726cdaebe1` (влят PR #106).

## Правила

- Приетите редове от extraction остават `ACCEPTED`. Липсата на отделна проверка спрямо оригинала е предупреждение `catalog_publication_source_review_required`. Съществуващите приети чернови се възползват без повторно потвърждение.
- Липсващите маркери са предупреждение `catalog_publication_hotspot_coverage` както за логическите групи, така и за стария assembly scope. Не се създават координати или маркери за липсващи позиции.
- Съществуващ непроверен маркер остава непроверен и е скрит при обичайния runtime режим `verified_only=true`. Геометрията, принадлежността на позицията и FK връзките продължават да се валидират.
- Публикацията остава блокирана при невалиден PDF/SHA, непълна част, неправилна връзка, нерешен конфликт, повредено extraction доказателство, текущо извличане, остарял digest или липсващи права. Избран списък без нито една потвърдена свързана част изисква попълване или поправяне на избора.
- Неприетите кандидати не се материализират. Реален `CONFLICT` остава блокиращ. Промяна на избора без повторно отваряне на редактора не скрива запазените конфликти.
- Предупрежденията не изключват бутона за публикация и нямат отделна процедура по одобрение. Действието „Проверих спрямо оригинала“ е допълнително и продължава да изисква валидно доказателство.

## Истински потвърждения и история

Новите runtime части използват `CONFIRMED_BUILDER_PUBLICATION`. Съвместимият `is_verified=true` означава потвърдена част, разрешена за runtime, **не** удостоверен PDF източник. За extraction частите се пренасят действителните оператор и време на приемане. Новите приемания записват `confirmed_at`; старите използват съществуващото време на създаване. При клониране то се запазва в новото доказателство. Ръчните части и комплектите се одобряват с нормалната публикация; новите комплекти използват `BUILDER_CONFIRMED_PUBLICATION`.

Валиден actor/source/version/fingerprint-bound inspection receipt от заредения оригинал може да се включи в същото еднократно потвърждение. Той се пази в доказателството и одита на приемането. Това **не** създава source-review решение и не превръща източника в `VERIFIED`. Изтекли или вече неприложими receipts не се подават автоматично. Изрично подадено невалидно доказателство се отхвърля от сървъра.

Отделните source attestations остават в съществуващия ledger. Публикацията не ги дописва, не променя кандидатите, първоначалните OCR стойности, редакциите или старите audit събития. Не е необходима DB миграция. Публикуваните ревизии остават immutable, а materialization и audit се изпълняват атомарно под каталожния lock.

## Приемателни доказателства

Всички нови записи са синтетични и се създават само в нови временни QA бази/схеми. Не е отварян или променян реалният Treatment D13 каталог.

| Случай | Части | Маркери | Отделни проверки | Резултат |
|---|---:|---:|---:|---|
| A | 59 | 59 | 1/4 | `ready=true`, 3 предупреждения, успешна публикация |
| B | 59 | 45 | 1/4 | `ready=true`, 4 предупреждения, 14 позиции без маркери |
| C | 59 | 0 | 1/4 | `ready=true`, успешна публикация без маркери |

И трите browser случая използват действителен upload, extraction, едно общо натискане за приемане на частите и публикация през UI. Проверени са runtime търсене и заявка, включително за позиция 59 без маркер в B/C. HTTP тестовете проверяват и пълния списък от 59 части, неизменени човешки решения/история и липсата на измислени маркери. [Browser proof](qa/catalog-ux05/browser-proof.json).

- [59/59, desktop](qa/catalog-ux05/publication-59-59-1440.png).
- [45/59, desktop](qa/catalog-ux05/publication-45-59-1440.png), [768 px](qa/catalog-ux05/publication-45-59-768.png), [390 px](qa/catalog-ux05/publication-45-59-390.png).
- [0/59, desktop](qa/catalog-ux05/publication-0-59-1440.png).

Локално: 40 целеви backend/runtime теста, допълнителни 3 теста за повредено доказателство/конфликт след промяна на избора/пренасочен оригинален източник и 1 за legacy scope — успешни. 45 frontend теста в 5 файла — успешни. `pnpm build`, `pnpm lint`, Python compileall и Ruff — успешни. Новите 16 HTTP сценария се изпълняват повторно и върху мигрирана PostgreSQL схема; още 2 PostgreSQL теста проверяват реално припокриващи се публикация/редакция и rollback след materialization.

Команди: `python -m pytest -q tests/test_catalog_ux05.py tests/test_catalog_publication.py tests/test_catalog_durable_review.py tests/test_catalog_guided_builder.py tests/test_catalog_ux04_runtime.py tests/test_catalog_review_fixes.py --tb=no --disable-warnings`; допълнителните случаи — `-k 'conflict_selection or evidence'`, `-k provenance_mapping` и `-k legacy`. Browser: `python tests/browser/run_catalog_ux05_qa.py`. Frontend: `pnpm exec vitest run src/features/catalogBuilder/CatalogPublicationPolicy.test.tsx src/features/catalogBuilder/GuidedParts.test.tsx src/features/catalogBuilder/GuidedBuilder.test.tsx src/features/catalogBuilder/DurableSourceReview.test.tsx src/features/catalogBuilder/CatalogUx.test.tsx --reporter=dot`.

Пълният CI изпълнява `python -m pytest -q -m "not postgres" --durations=10`, `python -m pytest -q tests/postgres --durations=10 --junitxml=postgres-test-results.xml`, всички frontend тестове, UX04 и UX05 browser QA, dependency/security/authorization/migration gates и изолираните image/release проверки. Окончателните job резултати и провереният HEAD се предават в PR.

## OCR регресии и граници

Повторени са `catalog_oem_layout_qa.py extract` + `compare`: **611/611** точни реда по петте полета в 24 страници/8 случая. [Сравнение](qa/catalog-ux05/oem-comparison.json).

Повторен е `catalog_adaptive_pdf_qa.py extract` за физически D13 страници 13 и 15: **30/30** точни реда по петте полета спрямо запазеното независимо валидирано извличане от UX04, със същия PDF SHA. Това е регресионно сравнение, без нова независима човешка транскрипция или одобрение. [Доказателство](qa/catalog-ux05/d13-regression.json). OCR алгоритъмът не е променян.

Локални Docker услуги, production база/инсталация и Cloudflare не са достъпвани. PostgreSQL и image проверките се изпълняват в изолирания GitHub CI. Не са променяни verified seed данни, source register, оригинални двоични документи, draft deletion графът или исторически публикации.

Известни граници: наличието на приети части не удостоверява пълнотата на производителския оригинал; липсващите маркери нямат графична навигация; отделната визуална проверка остава видима като незавършена, когато няма актуално реално решение. При 768 px общият header остава сгъстен по съществуващия layout, но публикацията и предупрежденията са достъпни без хоризонтално преливане.

Доставката е за независим review, без merge и deployment.
