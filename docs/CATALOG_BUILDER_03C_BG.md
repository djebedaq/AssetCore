# CATALOG BUILDER 03C — опростен работен процес

Начална база: `9048bee81888aad31fb520d0b0d5e03a8b2d89d6` (03A/PR #101 и 03B/PR #102).
Обхват: интерфейсът и необходимото additive представяне на съществуващите evidence/readiness данни.
Няма DB миграции, нови зависимости, роли, OCR стратегии или промени в resource limits.

## Предварителен UX audit

Прегледани са CatalogBuilder, AdvancedCatalogBuilder, SimpleCatalogBuilder, GuidedWorkspace,
GuidedSources, GuidedParts, DurableSourceReview, RevisionParts, RevisionHotspotEditor,
SourcePageViewer, WizardReview, ReferenceLinker, WizardMachines, guidedTypes, wizardTypes,
useDraftGuard, usePagePreview, свързаните тестове, преводи и responsive CSS.

| Сегашно действие | Класификация | Решение за 03C |
|---|---|---|
| Simple/Advanced превключване | Техническо, дублиран процес | Премахване от нормалния конструктор |
| Свържи съществуваща референция | Самостоятелна бизнес операция | Достъп от управлението на каталози |
| Каталог, метаданни, история | Основно + второстепенно | Изборът е основен; настройки и история са контекстни |
| Възел, логическа страница, вътрешни tabs | Основно + дублирана навигация | Една последователност от шест стъпки |
| Добави схема/списък, PDF преглед | Основно | Ясни роли и компактно обобщение, произволен брой източници |
| Премахване/подреждане на източници | Второстепенно | При конкретния източник, със съществуващите версии |
| Разпознаване на всички списъци | Основно | Един бутон; двупроходната логика от 03B се запазва |
| Retry | Само при проблем | При конкретния неуспешен/непълен източник |
| Таблица за всеки PDF списък | Дублирано представяне | Един общ изглед, идентичностите остават отделни |
| Четири inline полета за всеки ред | Претоварено редактиране | Избран ред с оригинал и редактор; удобен мобилен изглед |
| Технически бележки, mapping, raw evidence | Експертна поддръжка | Контекстни инструменти за избрания източник/ред |
| CSV, ръчно въвеждане, source mappings | Необходима специализирана операция | Контекстен инструмент; съществуващите API остават |
| Потвърждение на части и оригинален източник | Задължително човешко решение | Ясни отделни състояния, без автоматично VERIFIED |
| Причина, ръчна транскрипция, конфликти | Задължително според backend | Запазване на attestation, версии, fingerprints и audit |
| Point/rectangle/pan/числова геометрия | Основно + специализирано | Стандартно поставяне; допълнителни инструменти в контекст |
| Occurrences, варианти, undo, verify, resize | Необходими специализирани действия | Запазване, без постоянно показване на всички контроли |
| Readiness и publish | Основно | Сървърът остава authoritative; конкретни връзки за поправка |
| Три езикови имена, код, описание, активност | Уникални функции на стария Advanced | Контекстна поддръжка на каталог |
| Ревизия с изричен код/бележка, clone | Уникални функции на стария Advanced | Контекстно управление на ревизии |
| Bind/unbind машини, owner delete | Уникални административни функции | Запазени permissions и потвърждения |

Старият интерфейс има три нива на навигация, постоянно видими технически действия,
отделни таблици и повторено показване на оригинала. Няма измерване от реални потребители.
Браузърният baseline отчита само действията в възпроизводим QA сценарий.

## Защитни граници

Не се планират DB миграции или промени в OCR алгоритъма. 03A ledger, publication digest,
locking, candidate identity и 03B group context се използват директно. Обединяването на
таблицата е само визуално. Оригиналните PDF файлове и контролният JSON остават локални.
Production не е достъпвана. Не се извършват merge, deploy или реализация на 03D.

## Реализирана последователност

Една навигация с шест стъпки: **Каталог и възел → PDF страници → Разпознаване →
Проверка на части → Маркери → Публикуване**. Зареждането на черновата приключва преди
активиране на навигацията; закъснял workflow response не връща потребителя в стара стъпка.
Избраният каталог, категорията, производителят, моделът и ревизията са в компактния header.
Списъкът за избор на каталог се скрива след избор. Възелът се избира от списък в първата
стъпка и от компактен selector в следващите.

Създаването на възел създава първата празна логическа страница. Това **не** присвоява PDF.
Защитата срещу закъснял refresh използва текущия assembly scope. Допълнителни логически
страници, заглавия, пренареждане и изтриване остават достъпни за многолистни каталози.

Глобалният Simple/Advanced selector и вторият `AdvancedCatalogBuilder` са премахнати.
Уникалните му операции са преместени в контекстното „Управление на каталога“:
триезични имена, категория, описание, производител/модел, активност, owner deletion,
ревизии с изричен код и бележка, clone, bind/unbind и поддръжка на наследени visual sources.
Кодовете остават immutable според backend. Стандартното създаване има четири полета;
изричен код, други езикови имена и описание са незадължителни контекстни полета.
Всички съществуващи endpoints и permissions се запазват.

„Свържи съществуваща референция“ е отделно действие от списъка с каталози.
Association semantics от PR #100 не се променят. Repair kits, CSV, ръчно въвеждане,
source mappings, legacy assemblies и редактори остават в приложимия контекст.
Не е скрит целият стар конструктор в общо меню.

## PDF избор и разпознаване

Избраните източници имат ясна роля, физическа страница, файл и компактно обобщение.
Добавяне като схема/списък е изрично. Премахването и подреждането използват съществуващите
version checks. Няма ограничение за точно два списъка или за съседни страници/един PDF.
Оригиналният файл не се променя. Selection dialog поддържа Tab/Shift+Tab, Escape,
focus restoration и предупреждение при незапазен избор.

Един бутон „Разпознай частите“ изпълнява съществуващата 03B групова обработка:
независим първи pass, след това context-only retry на нуждаещите се източници.
Запазени са ограниченото последователно изпълнение, worker границата, actor-bound tokens
и durable attempts. UI показва обработени списъци, кандидати, конкретен неуспешен файл/страница
и retry само при проблем. Engine, PSM, DPI и fingerprints не са стандартни настройки.

## Единна таблица и оригинал

Един общ изглед показва **позиция, Part Number, описание, количество и източник**.
Има търсене, филтри всички/нуждаещи се от проверка/потвърдени и избор на валидните видими редове.
Последното е избор за последващо изрично човешко потвърждение, а не автоматично одобрение.
Невалидни, конфликтни, отхвърлени и вече приети редове не се включват автоматично.

Обединяването е визуално. Ключовете използват candidate identity; source occurrences и реални
варианти не се сливат по позиция, Part Number или еднакъв payload. Запазени са candidate/version,
source provenance и първичните стойности. За потвърдена част редакцията отваря съществуващия
part editor директно на съответния `part_id`, вместо да опитва забранен SAVE на ACCEPTED кандидат.

Изборът на ред отваря точната оригинална физическа страница отляво и четирите полета отдясно.
При доказана геометрия bbox се преобразува с оригиналната PDF rotation matrix. Проверяват се
крайни числа, положителни размери, граници и ориентация. Липсваща/невалидна геометрия означава
страница **без** измислен highlight. Zoom не добавя детайл; има достъп до оригинала през
съществуващия авторизиран download. Blob URLs са временни и се освобождават.
Няма публичен crop endpoint, нов image service или browser localStorage с review/evidence.

Единствената backend evidence промяна връща съществуващите width/height/rotation_matrix и ги
включва в HMAC claim. Resume ги възстановява от durable attempt. Legacy evidence без геометрия
остава четимо. Отрицателният тест подменя геометрията в claim: 422, без създадени части.

## Autosave, review и concurrency

Редакциите използват debounce 600 ms, blur и сериализирана SAVE опашка с версии по кандидат.
Бързи редакции на два различни източника не отменят взаимно таймерите си. Състоянията са
„Записва се“, „Запазено“, грешка и конфликт. Неуспешният SAVE запазва въведените стойности;
конфликтът не се прикрива с автоматично приемане на чуждата версия.
„Зареди текущия ред“ изисква потвърждение за отказ от конкретната локална редакция.
Незапазени стойности и отворени review/поддържащи форми предупреждават при напускане.

Преди потвърждение preview се подновява от durable API, включително след изтекъл token.
Candidate identity и версията трябва да съвпадат с показаните стойности. Конкурентна промяна
блокира потвърждението; не се изпращат старите стойности с нова версия. Докато има незапазена
редакция, source review и потвърждението са блокирани.

След неуспешен retry durable кандидати без confirmable preview остават видими и поправими.
UI не измисля HMAC token; следва успешен retry или задължителният server manual review път.
Нулеви/частични резултати, PENDING/CONFLICT и failed sources не стават VERIFIED.

Source review е компактен списък с оригинал, състояние и контекстна история на опитите.
Запазени са inspection receipt, reason/attestation, manual transcription, selection correction,
LINK_EXISTING/NEW_VARIANT/REJECT, actor, audit, fingerprints и версии. Изключването не става
универсален bypass. Refresh и logout/login възстановяват сървърното състояние.

## Hotspots и финална проверка

Стандартният hotspot editor работи inline: позиция → click върху оригиналната схема →
съществуващо autosave/verify → следваща непроверена позиция. Следващата позиция се избира по
VERIFIED state, включително когато вече има непроверен marker. Тестът различава това от
прескачане директно към следваща позиция без никакъв marker.
Компактният прогрес и part/variant контекст остават видими. Point, pan, zoom/fit и undo са
достъпни; rectangle, resize, numeric geometry, additional occurrences, overlay и ръчно verify
са контекстни. Запазени са normalized coordinates, versions и multi-touch cancellation.
Pan/pinch не създава marker.

При липсващ/несъвпадащ callout интерфейсът насочва към човешка проверка, без да измисля
позиция. D13 48/38 остава неразрешено. Точните 30 extraction кандидата не са 30 verified hotspots.

WizardReview използва server readiness, показва обобщение и конкретни възел/файл/физическа
страница/позиция с действие „Поправи“. Backend добавя само тези display labels и броя валидно
reviewed sources от съществуващото proof. Publication invariant, digest, locking и direct API
защитите не се променят. Един publish бутон изпраща текущия digest и изрично потвърждение.

## Responsive, достъпност и езици

Desktop: една компактна таблица и сравнение PDF/редактор в две колони. Mobile: компактни
таблични карти и редактор на избраната част с достъпен оригинал; няма широка input таблица.
Премахнат е наследеният table min-width, който иначе скрива Part Number извън мобилната карта.
Браузърните assertions проверяват и document overflow, и вътрешния overflow на parts изгледа.
Проверени ширини: 390, 768 и 1440 px.
Touch targets не променят размерите на marker overlay: общият минимален размер на бутоните
изключва геометричните маркери, които запазват съществуващия отделен hit target. Реални touch
поставяния при трите ширини проверяват и съответствието на видимите размери с normalized geometry.

Има semantic buttons/labels/status/alerts, keyboard row selection, editor heading focus,
видим focus ring, modal focus trap/restoration, Escape и 44 px mobile action targets.
Проверен е отказът от изхвърляне на незапазена форма. Това е автоматизирана проверка на
конкретни accessibility поведения, не сертификация за пълно WCAG съответствие или
твърдение за проведено screen-reader потребителско проучване.
Новите ключове са в `catalogUxTranslations.ts` с compile-time и тестова BG/EN/RU parity.

## Измерени действия преди/след

Baseline е реален браузърен прогон върху непроменения 03B main, преди продуктовите промени.
Отчитат се button/checkbox/summary clicks, Enter и select/file change. Въвеждането на текст
не се брои; навигацията след refresh и повторните проверки са отделни фази. Няма измислени
резултати от хора. OEM extraction и контролните данни са еднакви в двата прогона.

| Фаза | 03B | 03C |
|---|---:|---:|
| Каталог, възел и избор на схема 12/списъци 13,15 | 18 | 18 |
| Разпознаване и отваряне на review | 1 | 2 |
| Избор и потвърждение на 30 части | 21 | 2 |
| Общ основен път до потвърдените части | **40** | **22** |

Намаление с 18 отчетени действия (45%) в този скриптиран път. Самият extractor се стартира
с един click и в двата случая. Допълнителното действие в 03C отваря изричната review стъпка.
Baseline изискваше 20 отделни OCR checkboxes; останалите 10 чисти реда вече бяха избрани.
Не се твърди намаление на всички възможни сценарии или измерено време на реални оператори.

## QA резултати и възпроизводимост

Реален D13 SHA-256: `e9540c2af79802d000f186381c403dfbca6ae6b58ecb6cb13b9ecec862558e42`.
Оригиналът и expected JSON остават локални. Expected JSON се чете единствено след extraction,
в отделния comparator. Не се подава на app server, worker или Linux контейнера.

| Проверка | Изпълнен резултат |
|---|---|
| Windows/Edge, реален D13 през нормалния UI | 20/20 + 10/10; една таблица; SHA/page; edit/refresh; re-extraction без дубликати; source review refresh; hotspot blockers |
| Linux Docker D13, 3 повторения | 3 × (20/20 + 10/10), всички 4 полета + SHA/physical page; 0 останали subprocess-и |
| Full Vitest | 604 PASS / 66 файла (`node node_modules/vitest/vitest.mjs run --maxWorkers=2`) |
| Typecheck / ESLint / production Vite build | PASS; съществуващото предупреждение за големия общ app chunk остава |
| Backend durable/adaptive/publication/wizard/evidence | 69 PASS, 2 platform SKIP на Windows; Unix process-group cases се изпълняват в Linux CI |
| Evidence geometry и подмяна на HMAC claim | 2 PASS, включително legacy no-highlight и 422 tampering |
| Ruff / protected Alembic history / authorization inventory | PASS |
| Catalog V2 / catalog translation checks | PASS: 611 записа, 9/9 непроменени source fingerprints |
| Production-oriented изолиран Linux image build | PASS; non-root runtime, без OEM PDF/expected/.env в build context |
| LibreOffice / visual appendix / Builder official DOCX/PDF | PASS в read-only Linux image |
| Offline OCR / adaptive OCR smoke | PASS: masks, rotation, skew, resolutions, borderless, partial cells |
| PostgreSQL 16 image clients | PASS: pg_dump/pg_restore/psql 16.15 |

Full backend SQLite, PostgreSQL transactions/backup compatibility, dependency audits и release
checks се изпълняват от съществуващия **Build check** workflow върху PR HEAD. Финалният CI статус
и точните резултати са в PR checks и машинночетимия QA отчет; не се заменят с frontend readiness.
Локалният full frontend прогон с неограничени workers беше прекъснат при конкуриращ се QA load;
повторният ограничен прогон завърши с 604 PASS. Прекъснатият опит не е отчетен като PASS.

Основни команди: `pytest -q tests/test_catalog_durable_review.py tests/test_catalog_adaptive_extraction.py
tests/test_catalog_publication.py tests/test_catalog_wizard.py tests/test_catalog_evidence_preview.py`;
`python tests/browser/run_catalog_simplified_ux_qa.py <local-original> <local-control>`;
synthetic browser runner `run_catalog_durable_review_qa.main(browser_script=.../catalog_simplified_synthetic.mjs)`;
`python scripts/catalog_adaptive_pdf_qa.py extract <local-original> --pages 13,15 --runs 3 --output <report>`
и **отделно** `compare <report> <local-control> --output <comparison>`.

Linux: network none, read-only root, 1 GiB container, 2 CPUs, 64 PIDs, /tmp 192 MiB за D13.
Worker limits остават 45 s / 1 GiB и съществуващият pixel/cell budget. Измерванията са sampling
на process tree (20 ms), включително controller; queue wait е 0 в изолирания последователен прогон.

| PDF страница | Wall time, 3 прогона | Peak tree RSS | CPU seconds | Peak процеси |
|---|---|---|---|---:|
| 13, image/cell OCR | 12.0221 / 4.2841 / 4.2351 s | 532.39 / 350.46 / 350.96 MiB | 8.37 / 4.18 / 4.25 | 3 |
| 15, native fast path | 1.5141 / 0.6727 / 0.6736 s | 174.48 / 174.33 / 174.91 MiB | 1.40 / 0.62 / 0.65 | 2 |

Първият прогон включва cold runtime overhead; това не е benchmark на production натоварване.
Машинночетимото exact-field доказателство е [d13-linux-exact.json](qa/catalog-builder-03c/d13-linux-exact.json).
Screenshots в PR са от реално работещия браузър със **синтетичния** PDF, не декоративни mockups.
OEM screenshots остават локални; не се публикуват и не са изпращани към външна OCR/AI услуга.

## Регресии, ограничения и 03D

Новите тестове покриват една таблица с отделни еднакви occurrences, partial кандидати, bulk selection,
две бързи редакции, stale SAVE, отказ/потвърждение на reload, token renewal със/без concurrent change,
невалиден пропуснат ред след частично потвърждение и неуспешен refresh,
възобновяване след stale confirmation с презареждане само на действително променения кандидат,
retained candidates след failed retry, empty-page creation race, BG/EN/RU и rotated/invalid geometry.
Реалният Edge сценарий с два едновременно отворени таба доказва запазването на несъхранения
текст при stale autosave, нула създадени части при stale confirmation и успешно продължаване
след изрично зареждане на текущия ред. Непроменените редове не се маркират като конфликтни.
Съществуващите GuidedParts тестове обработват 1/2/3/4/7 списъка и failed middle source/context retry.
CatalogMaintenance и реалният CatalogBuilder проверяват запазените административни операции,
immutable кодове, clone/unbind confirmations и актуалния publication digest.
03A/03B, PARTS-DOC, authorization, historic snapshots и PostgreSQL regressions остават задължителни.

Наследените drafts използват съществуващия fail-closed ledger преход; няма автоматичен VERIFIED
backfill. PUBLISHED/RETIRED, signed DOCX/PDF, snapshots и оригинални артефакти не се променят.
Няма изменения на seeds, machine register, Falch номерация, historic business records, роли,
permissions, DB schema или OCR алгоритъм. QA каталозите са само в изолирани временни бази.

03D остава общото интеграционно hardening, допълнително acceptance на производители/големи каталози
и multi-user/resource stress. D13 publication не е заявена: 48/38 и всички hotspots изискват
реално човешко разрешаване. Успешна крайна UI публикация се доказва само със синтетичните
десет видими callouts. Няма автоматичен merge, release, production deployment или започване на 03D.
