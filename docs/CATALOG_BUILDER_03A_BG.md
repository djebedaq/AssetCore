# Catalog Builder 03A — постоянна проверка на източниците

Обхватът е само 03A. PDF/OCR стратегиите, ресурсните бюджети, hotspot editor-ът и основната последователност на конструктора са запазени. 03B/03C/03D не са започнати. Production не е достъпвана; не са изпълнявани merge или deployment.

## Данни и миграция

Additive Alembic `20261009_0033`, след `20261009_0032`, създава пет таблици:

| Таблица | Съдържание |
| --- | --- |
| `catalog_extraction_sessions` | Точен набор assignments, документни SHA-256, физически страници, роли, ред и selection digest за логическа страница или legacy възел |
| `catalog_extraction_sources` | Отделни processing/review състояния, текущ опит, монотонна версия и приложимост на одобрението |
| `catalog_extraction_attempts` | EXTRACTION/MAPPING/CARRY_FORWARD/MANUAL, lease, оператор, резултат, грешка и evidence digest |
| `catalog_extraction_candidates` | Оригинален ред, запазени човешки стойности, устойчива идентичност, версия, решение и връзка към потвърдената част |
| `catalog_source_review_decisions` | Историческо изрично одобрение за точна версия/fingerprint, оператор, дата, основание и digest на доказателството за отваряне на оригинала |

Има unique constraints за selection/source/candidate identity, проверки за допустимите технически състояния и положителни версии, foreign keys към ledger/revision/user и индекси за lookup. Историческите assignment/part идентификатори са snapshots: премахване на текущо assignment не изтрива оригиналното доказателство. Ledger source пази FK към споделения оригинален PDF blob, включително при legacy stored bytes. Защитеният GET extraction-sources/{id}/original запазва четимостта на историческата физическа страница след корекция на избора и премахване на неизползван draft artifact; той не издава receipt за ново одобрение. Съществуващите part unique constraints остават.

Няма backfill на VERIFIED, промяна на исторически миграции или редакция на бизнес записи. Downgrade е разрешен само за празен ledger; при записана работа отказва да изтрие история. Изключването на OCR през съществуващата конфигурация не отменя publication gate.

Owner deletion също отказва да изтрие каталог с ledger история и показва преведен blocker. Новите actor foreign keys имат изрично прегледани етикети и блокират изтриването на съответния потребител. Catalog deletion взема същия catalog row lock преди dependent table locks; PostgreSQL regression проверява конкуренцията с човешко одобрение без загуба на история.

## Публикация и конкурентност

Преди публикация backend придобива каноничния catalog lock. PostgreSQL използва FOR UPDATE; SQLite придобива write lock с update на същия catalog ред. ORM cache се обновява след lock, включително при дълго живяла сесия. Всички нови review операции и засегнати source/part/mapping операции споделят тази граница.

За ВСЯКА текущо избрана SPARE_PARTS_LIST страница се проверяват текущият selection session, завършеният успешен опит и неговите evidence, липсата на PENDING/CONFLICT, изричното човешко решение и неговата точна версия/fingerprint. Fingerprint включва selection/source metadata, версията на логическата страница, потвърдените части и source mappings, текущия опит и кандидатите. Публикационният digest включва и review proof. Съществуващите PDF SHA/page, part, hotspot, kit и PARTS-DOC проверки остават в сила.

Part/source/mapping промяна обезсилва приложимите одобрения постоянно и добавя audit. Връщане към предишни стойности или повторно използван SQLite идентификатор не възстановява одобрението. Остарял digest/version/inspection receipt връща конфликт; директен publish API не прескача проверките.

При 5/0/5 средният източник остава непроверен, логическата страница не е COMPLETE, readiness е false и publish отказва. Успешната обработка и броят намерени редове никога не дават автоматично VERIFIED.

## Човешка работа и нулеви резултати

UI показва всеки физически източник, processing/review състояние и история на опитите. Операторът отваря защитен оригинален PNG и сравнява всички части. Backend издава HMAC receipt, обвързан с actor/source/session/version/fingerprint и 900 секунди. Основанието и изричното одобрение се записват в базата и audit. Receipt доказва получаването на точния оригинал; човешката оценка остава отговорност на упълномощения оператор.

Нулев/неуспешен/legacy резултат може да се завърши чрез изрично удостоверена ръчна транскрипция, само при записани части, свързани с точния източник, и разрешени кандидати. Нулева страница без части не може да бъде VERIFIED. Няма EXCLUDED флаг, който да пропусне все още избран списък.

Грешен избор се коригира отделно: точен оригинал, основание, актуална версия, липса на активна обработка, отхвърлени кандидати и липса на mapped parts. Audit запазва класификацията WRONG_SELECTION, стария source и fingerprint; assignment се премахва от текущия избор. Старите DELETE/classify endpoints, включително изтриване на цял legacy възел, не могат тихо да премахнат обработен източник. Това отличава документирано поправения избор от непрочетен списък, който изисква retry или транскрипция.

Човешките поправки на непотвърдени редове се записват автоматично с optimistic version. Потвърдените части се редактират през съществуващия parts editor. Resume възстановява резултатите и издава нов краткотраен actor-bound preview token без повторен OCR. Logout/refresh/изтекъл token не изтриват решенията. RUNNING се записва преди worker; изтекъл lease се възстановява като CANCELLED с audit, а закъснял стар worker не отменя по-нов опит.

След FAILED/CANCELLED retry последният успешен опит за същия точен източник остава редактируем и може да бъде потвърден с текущите candidate versions. Processing състоянието остава FAILED/CANCELLED; използването на старите запазени редове не възстановява одобрение или OCR успех. Финалното source решение изисква изрично сравнение и ръчна транскрипция. RUNNING и по-нов успешен опит не позволяват използване на стар preview.

## Повторно извличане и наследени чернови

Candidate identity използва точните оригинални клетки в рамките на точния източник, независимо от bbox. Малка геометрична промяна не създава нова част и не презаписва човешки Part Number. Променен OCR прочит на същата позиция, двусмислено съвпадение, дублиран оригинален ред или изчезнал непотвърден ред създават CONFLICT. Операторът избира връзка към вече поправена част, отделен вариант за преглед или мотивирано отхвърляне. Няма manufacturer-specific корекции или автоматично сливане на реални варианти.

PUBLISHED/RETIRED digest и данни не се променят. Наследена или клонирана DRAFT получава ledger при отваряне/обработка, без наследено одобрение. Съществуващите части и документи остават четими; операторът отваря оригинала и потвърждава текущите данни. При промяна на избора запазените поправки могат да се пренесат с CARRY_FORWARD evidence, но одобрението не се наследява.

## Запазен обхват и ограничения

Machine.id, 19-машинният регистър и Falch номерацията, verified seed/source registers, factory fingerprints, shared references, repair kits, заявки, authorization, audit, исторически официални документи, подписани DOCX/PDF и snapshots не са редактирани. Оригинални OEM PDF не се commit-ват и не се изпращат към външна услуга. Новите endpoints изискват съществуващото parts.manage; няма нови роли или инфраструктура.

03B остава за adaptive native/image/cell OCR, Linux OCR accuracy и multi-page context; 03C — пълното опростяване и обединена таблица; 03D — реалният D13 browser acceptance и общите benchmarks. 03A не твърди D13 30/30 или разрешено 38/48 hotspot несъответствие.

## Проверки

Локални изпълнени проверки (командите са от корена, освен frontend):

| Команда | Резултат |
| --- | --- |
| `python -m pytest -q tests/test_catalog_durable_review.py tests/test_catalog_durable_review_migration.py --tb=short` | 14 passed; 8 предупреждения от съществуващи зависимости/SQLite migration introspection |
| `python -m pytest -q tests/test_registry_catalog_02.py -k test_builder_drafts_excluded_published_revision_pinned --tb=short` | 1 passed, 10 deselected; shared reference pinning assertions са запазени |
| `python tests/browser/run_registry_catalog_postgres_qa.py tests/postgres/test_catalog_durable_review_postgres.py -x` | 5/5 PASS на PostgreSQL 16 след TCP readiness поправката; новият owner deletion concurrency случай се изпълнява допълнително и в пълния Linux CI |
| Целевият прогон на route inventory, Builder permissions, incoming user FK labels и owner catalog deletion | 5/5 PASS; точните route counts са актуализирани за седемте нови permission-protected endpoints, без премахнати assertions |
| Целевият прогон на durable review, migration, guided/publication/wizard/final audit и release infrastructure | 44 passed преди финалното допълнение за архивирания PDF; то е покрито от 14-те проверки по-горе |
| `pnpm typecheck`, `pnpm lint`, `pnpm exec vitest run --maxWorkers=1`, `pnpm build` във frontend | PASS; 64 файла / 587 теста; допълнителната regression проверка за технически бележки: 5/5 в GuidedParts; Linux CI изпълнява целия разширен набор |
| `python tests/browser/run_catalog_durable_review_qa.py` | PASS през реален Edge: поправка преди confirm, 2 source blockers, refresh, logout/login, 768/390 px, точни 10 синтетични части и 10 видими callouts, успешна публикация; няма page errors |
| `python scripts/verify_release.py --output .tmp/catalog-03a-release-final` | 26/26 PASS, включително 19 проверени машини и 611 проверени части |
| `python -m ruff check backend/app backend/alembic backend/scripts scripts tests`, `python -m compileall -q backend/app backend/alembic backend/scripts scripts tests` | PASS |
| `python backend/scripts/validate_migration_history.py --require-all-protected`, `python backend/scripts/validate_authorization_inventory.py` | PASS; 33 защитени миграции, старите 32 hashes са непроменени; новите routes използват централизираното permission |
| `PYTHONPATH=backend python backend/scripts/catalog_v2_validation.py`, `PYTHONPATH=backend python backend/scripts/build_catalog_translations.py --check` | PASS; frontend тестовете проверяват BG/EN/RU key parity |
| `python scripts/audit_dependencies.py python`, `python scripts/audit_dependencies.py frontend`, `python -m pip check` | PASS; няма нови зависимости |

Linux CI в [PR #101](https://github.com/djebedaq/AssetCore/pull/101) изпълнява пълните `python -m pytest -q -m "not postgres" --durations=10`, `python -m pytest -q tests/postgres --durations=10`, PostgreSQL 16 migration/encrypted backup/restore, production Docker build и всички image smoke проверки, включително PARTS-DOC/LibreOffice/OCR и read-only non-root runtime. Точният завършен статус, SHA и брой тестове се записват в PR описанието при предаване; Checks са авторитетни за текущия head.

Ограничения на локалната среда: пълният Windows backend прогон е прекъснат, а локалният Docker build е прекъснат при продължителен export на layers; те не се отчитат като PASS. Windows документният smoke достига публикация, но няма работеща LibreOffice конверсия; действителният DOCX/PDF round trip се проверява в Linux Docker CI. QA PostgreSQL launcher-ът вече изчаква крайния TCP сървър, вместо временния Unix-socket init server, който причини ранните connection failures. Не са увеличавани parser/worker лимити или concurrency assertions.

Локалните browser данни са синтетични и се създават само в отделна временна QA база; проверените seed записи се използват без промяна. QA launcher-ът премахва само своя случайно именуван PostgreSQL контейнер и неговите volumes. Предварително наличните untracked документи, OEM PDF и QA данни са запазени. Финалният diff няма промени в seed/source registers, OEM binaries или исторически бизнес материали.
