# CATALOG BUILDER 03D — окончателно приемане и release readiness

## 1. Executive summary

**NO-GO за общо production внедряване. PR остава draft / NOT READY и неслят.**
Пет възпроизведени дефекта са поправени. Реалният D13 е точен 30/30 в три Linux
повторения и в Edge; synthetic каталог преминава целия UI до публикация и повторно
отваряне. Publication, durable review, concurrency и encrypted restore имат нови
доказателства. Но общото автоматично OEM приемане е **FAIL**: осем други налични
каталога / 24 физически страници / 611 контролни записа не се извличат точно.
Същият проблем се възпроизвежда с предходния 03C image. Зелен CI не го отменя.

Няма production достъп, merge, deployment, schema migration или OCR алгоритмична
промяна. Оригинални OEM PDF, редове, crops и screenshots не се включват в PR.

## 2. Начална версия и обхват

База `1bdb74b1c6d78d99ac4072690b66b5bf7b8d6be0`, проверен актуален `origin/main`.
03A `becc09f3715dbd66780779b33e9e2b834f28ff74`, 03B
`9048bee81888aad31fb520d0b0d5e03a8b2d89d6` и 03C са предшественици.
Отделен branch `feature/catalog-builder-03d-final-acceptance`; [PR #104](https://github.com/djebedaq/AssetCore/pull/104).
Наличните untracked OEM/QA материали са запазени; няма reset/clean.
Product fixes са в `4982f1994c6499300559558834799c21aca3a3c8` и предходния му
03D commit. [Implementation fingerprints](qa/catalog-builder-03d/implementation.json)
свързват точните модули с доказателствата, независимо от последващи QA/docs commits.

## 3. Инвентаризация на 03A / 03B / 03C

Прочетени са трите отчета и архитектурният review. Началната матрица
[QA README](qa/catalog-builder-03d/README.md) разделя старите доказателства от новото
приемане. 03A осигурява пет durable таблици, actor-bound inspection, fingerprints,
versions и authoritative publication gate. 03B осигурява независими native/layout/
image-cell предложения, физическо coverage и групов контекст. 03C предоставя
шестстъпковия UI, общата таблица, autosave и опростения hotspot editor.
Нито един от тези механизми не се заменя.

## 4. Реален D13 — Linux и Edge

Original SHA-256: `e9540c2af79802d000f186381c403dfbca6ae6b58ecb6cb13b9ecec862558e42`.
Схема 12, списъци 13 и 15; възел `TCD13A.01 Chassis Assembly-2`.
Три независими extraction повторения в non-root, read-only, network-none Linux
контейнер. Expected JSON не е монтиран в контейнера и се чете единствено от
отделния host comparator след приключване на извличането.

| Повторение | PDF 13 | PDF 15 | Общо | SHA / physical page | Останали descendants |
|---|---:|---:|---:|---|---:|
| 1 | 20/20 | 10/10 | 30/30 | PASS | 0 |
| 2 | 20/20 | 10/10 | 30/30 | PASS | 0 |
| 3 | 20/20 | 10/10 | 30/30 | PASS | 0 |

Всички четири полета са exact, включително водещи нули и оригинална пунктуация.
[Linux exact comparison](qa/catalog-builder-03d/d13-linux-exact.json) съдържа само
броеве, hashes, версии, quality и ресурси. Edge премина 7 проверки:
едно разпознаване, обща таблица 20+10, поправка/refresh/възстановяване на оригинала,
потвърждение, re-extraction със същите candidate IDs, source review и блокирано
публикуване. [Browser D13](qa/catalog-builder-03d/browser-d13.json).

Callout 48 срещу позиция 38 остава неразрешен OEM въпрос. Интерфейсът показва
задачата за сравнение с оригинала и липсващото hotspot coverage. Няма измислен
marker, автоматична подмяна или публикация на D13. Extraction PASS не е hotspot PASS.

## 5. Други реални документи — установен blocker

[Document inventory](qa/catalog-builder-03d/document-inventory.json) описва само
hash/page/word/image/rotation metadata. Налични са D13/P200E/X25 и verified
Falch/HYDWIN library originals. Hammelmann original липсва в разрешения workspace.

Независимият corpus extractor не чете verified control JSON. Comparator се
изпълнява след записването на private extraction output и проверява original SHA.
Контролите са съществуващите verified source записи, а не нови измислени fixtures.

| Каталог | Контролни записи | Кандидати | Точни пълни редове* |
|---|---:|---:|---:|
| Falch 1000 drive pump | 34 | 0 | 0 |
| Falch 1000 liquid part | 46 | 0 | 0 |
| Falch 1000 wheel jet | 164 | 61 | 0 |
| Falch 500 pump | 65 | 0 | 0 |
| Falch 500 unloader valve | 65 | 33 | 0 |
| Falch 500 valve 500bar | 32 | 0 | 0 |
| Falch 500 wheel jet | 147 | 0 | 0 |
| HYDWIN Fussen plunger pump | 58 | 0 | 0 |

* Position, Part Number, original description (any exact existing DE/EN/FR source
description), numeric quantity и quantity_raw; physical page и SHA са отделни
проверки. Запазен е строгият ordered field comparator и е добавен duplicate-consuming
multiset comparator, защото геометричният обход на панели може да има различен ред.
60 position/number occurrences съвпадат, но не покриват exact description/quantity
comparator. Всичките 94 кандидата са без quantity и имат QUANTITY warning;
34 кандидата нямат съответстваща position/number двойка. Нито една страница не е
представена като COMPLETE_CANDIDATES: всички са NEEDS_REVIEW / NOT_REVIEWED.

[Corpus summary](qa/catalog-builder-03d/corpus-summary.json),
[field/page comparison](qa/catalog-builder-03d/corpus-comparison.json) и
[03C baseline comparison](qa/catalog-builder-03d/corpus-baseline-comparison.json)
доказват проблема. При еднакъв runtime/model set кандидатните payload/provenance
и accuracy/quality метриките съвпадат с 03C. OCR/native module fingerprints са
еднакви; разликите са process boundary и новият capacity module.
Това е съществуващо ограничение на 03B/03C, не регресия, въведена от 03D.

Наблюдават се невалидни native metadata tables, неразрешена word geometry,
многоредови/многоезични заглавия и horizontal panels с повтарящи се семантични
колони. Например HYDWIN има 10 колони / 29 физически bands за 58 контролни записа;
schema margin е нула. Това не се решава безопасно с намаляване на confidence guards
или manufacturer-specific координати. Точното общо OEM приемане е спряно.
P200E/X25 exact accuracy е NOT RUN: няма независим контрол. Hammelmann е NOT RUN:
няма оригинал. Няма твърдение за доказана точност за тях.

## 6. N-page extraction

Edge: 1 списък → 5 кандидата; 4 → 20; 7 → 35. При седем списъка четвъртата HTTP
заявка е прекъсната преди достигане до app server. Другите шест запазват 30
кандидата. Refresh ги възстановява; retry извиква само пропуснатата физическа
страница, след което има 35 отделни candidate IDs и по един успешен attempt на
източник. Нула автоматично VERIFIED. [Browser N-page](qa/catalog-builder-03d/browser-multipage.json).
Backend regressions покриват 1/2/3/4/7, несъседни страници, различни документи,
configured order и несъвместими таблици. Няма бизнес лимит „точно две“.

## 7. Групов контекст

`test_n_selected_lists_and_later_page_context_resume` повтаря първи независим pass
и втори pass към по-ранна проблемна страница с профил от по-късна съвместима таблица.
Foreign-document профили изискват доказана съвместимост; не пренасят стойности или
чужди абсолютни координати. `test_group_ocr_releases_transaction_and_rejects_concurrent_review`
доказва реален PostgreSQL NOWAIT lock по време на OCR: няма дълга DB transaction,
RUNNING е видим, stale review се отказва. Алгоритъмът не е променян в 03D.

## 8. Human corrections и reconciliation

Full suite повтаря expired preview resume, saved human Part Number + bbox drift,
конфликт при различен OCR номер, два идентични физически реда, explicit link,
отделни occurrences и SQLite reused-ID tombstones. Човешката поправка не се
презаписва; старият OCR номер не става автоматичен нов вариант.
Edge проверява два реални таба: stale autosave запазва незаписания текст,
изрично reload вижда чуждата записана поправка, stale confirmation създава нула части.

## 9. Пълнота и publication gate

`test_5_zero_5_blocks_complete_readiness_and_direct_publish` доказва source 2
непроверен, COMPLETE отказан, readiness=false, direct publish отказан и нула
нови published ревизии. Допълнителните regressions покриват PENDING/CONFLICT,
непроверен hotspot, assignment/hash/mapping промяна, stale digest, part edit,
legacy draft без review и неподходящо изключване. PostgreSQL проверява publish
със cached graph срещу конкурентна поправка. Gate, locks и digest не са променяни.
Browser direct API отказва преди review; synthetic публикацията успява единствено
след действителното сравнение/потвърждение на оригиналните QA страници и markers.

## 10. Hotspot acceptance

Synthetic PDF съдържа десет видими QA callouts плюс втори original diagram с
реално повторена позиция 1. Edge поставя/записва/проверява point markers чрез touch
при 390/768/1440; geometry се сравнява с normalized server стойностите.
На втората схема са изпълнени touch pointer cancellation, rectangle draw, mouse
move/resize, verify/unverify с readiness blocker, stale PATCH → 409, Undo/delete,
ново поставяне, втора occurrence, zoom/pan без промяна на geometry.
След публикация и повторно отваряне всички source/part/coverage/hotspot записи са
точно същите. Истински OEM markers не са фабрикувани.

## 11. Full browser UX

[Synthetic browser evidence](qa/catalog-builder-03d/browser-synthetic.json): 10 PASS,
нула page errors. Няма global Advanced Mode, има шест стъпки, една extraction
операция и обща таблица. Проверени са original PDF comparison, keyboard editor,
focus trap/Escape/focus restore, unsaved modal cancellation, BG/EN/RU, logout/login,
responsive 390/768/1440 и липса на page overflow. N-page QA използва и 1920 px.
Source switch cancel запазва reason/manual/link/original; accept изчиства всичко и
зарежда точната нова страница. LINK_EXISTING е обвързан с конкретния кандидат и
source/version/fingerprint. Screenshot доказателствата са **само synthetic**:

- [Mobile parts](qa/catalog-builder-03d/screenshots/parts-390.png)
- [Tablet touch markers](qa/catalog-builder-03d/screenshots/touch-hotspots-768.png)
- [Second scheme rectangle](qa/catalog-builder-03d/screenshots/rectangle-second-scheme-1440.png)
- [Published reopened revision](qa/catalog-builder-03d/screenshots/published-reopened-1440.png)

Не е извършвано формално потребителско или сертифицирано screen-reader изследване.

## 12. Multi-user concurrency

Три независими Python web-controller процеса при два slots: точно два допуснати,
третият получава busy преди parser. Kill на holder освобождава slot. На Unix worker
наследява descriptor и продължава да държи lease при смърт на web parent; неговото
прекратяване освобождава slot. Private-directory/file/symlink отрицателни тестове
са fail-closed. Lock файловете не се unlink-ват, за да не възникне втори inode.
Scope е един runtime/container с общ temp namespace; това не е cluster quota.

Реални PostgreSQL overlapping transactions: два candidate edits, source review,
assignment/review, delete/review и publish/edit. Нов тест с owner и отделен QA
director изисква собствени receipts: replay на чужд receipt се отказва; актуалните
конкурентни approvals завършват 200/409, точно един audit decision за новата version.
Локалният нов PG тест: 1 PASS / 59.88 s в собствен 512 MiB / 1 CPU / 64 PID container,
почистен във finally. Full PG CI: 97 PASS / 616.14 s.

## 13. Fault injection

Повторени са worker crash/timeout с действителен child и kill-group cleanup,
невалиден/повреден/encrypted/oversized PDF, OCR unavailable, partial/empty cells,
липсващ физически band, word/pixel/cell limits, expired token, stale fingerprint,
double confirmation, failed retry и interrupted attempt recovery.
Новите worker-output случаи `{`, JSON list и невалиден UTF-8 връщат контролирана
422 грешка вместо native exception. Unix memory probe стартира real worker.main
и опитва allocation над RLIMIT_AS; отказът е контролиран, без реално 2 GiB host
allocation, след което lease се използва от нормален parser.
Browser fault е клиентско connection reset + refresh; successful sources остават.
Partial evidence остава durable, когато е успяло да се запише. Неизвестен резултат
не се превръща във VERIFIED.

## 14. Ресурси и performance

Бюджетът е предварително зададен: един собствен Linux контейнер, 2 CPUs / 1 GiB /
64 PIDs / 192 MiB tmpfs; до три synthetic contenders / два parser workers.
45 s worker timeout, 1 GiB address-space и съществуващите pixel/cell/word budgets
не са увеличени. Native fast path остава без тежък OCR.

| Страница / режим | Wall time (s) | Peak sampled process-tree RSS |
|---|---|---:|
| D13 13, три отделни worker-а | 4.3361 / 3.7391 / 3.6821 | 351.15 MiB |
| D13 15, native | 0.6732 / 0.6237 / 0.6236 | 175.02 MiB |
| Два едновременни OCR на 13 | 7.1982 общо | 970.12 MiB (RSS sum) |

Concurrent cgroup memory.peak е 666050560 bytes (~635 MiB), memory.events има нула
OOM/max events, pids.peak=14 (включва threads), лимит 64. Sampled CPU е 10.67 s
за измерения concurrent extraction interval; cgroup CPU counters обхващат целия
контейнер, включително startup/runtime/model fingerprinting. RSS sum брои shared
pages повече от веднъж и не е container memory charge. Нула останали descendants,
нула timeout/error при шестте sequential и двата concurrent D13 worker-а.
Busy е immediate, queue wait=0; няма обещана FIFO опашка.

[Performance evidence](qa/catalog-builder-03d/performance.json),
[concurrent exact comparison](qa/catalog-builder-03d/d13-concurrency-exact.json).
Медианите са описателни за n=3; P95 не се оценява. Всеки page има fresh worker,
но OS cache не е reset-ван, следователно няма сертифицирано cold-boot измерване.
Спрямо предходните ориентири ~4.2/.67 s и ~350 MiB няма видимо съществено влошаване;
това не е production SLA или доказателство за продължително натоварване.
Начален паралелен local build/browser/fault опит е INTERRUPTED при малък host RAM
резерв; собствените fault процеси са спрени, последващите тежки проверки са sequential.

## 15. PostgreSQL и миграции

Няма нова schema или migration. Всички 33 protected migrations се валидират;
head е `20261009_0033`. PG проверява constraints/indexes, no VERIFIED backfill,
transaction rollback, stale versions и overlapping locks. SQLite full suite и
browser използват отделни временни бази. Legacy drafts остават непроверени;
clone на published revision не наследява approval за новите assignments.
Новият shared schema assertion сравнява index names/columns/uniqueness,
unique/check constraints и FK targets/ondelete след upgrade на SQLite и PG.
Локално: SQLite 1 PASS / 3.07 s, PG 1 PASS / 48.90 s. Първият SQLite опит FAIL
беше stale cached PRAGMA reflection в pooled connection след external Alembic
DROP/recreate; sqlite_master потвърди налични индекси. Свежата връзка решава QA
fixture проблема, без отслабване на assertion или промяна на schema/history.

## 16. Encrypted backup/restore

Разширен е съществуващият PG rehearsal от pre-0025 база до 0033. Преди backup
се създават normal-service extraction, човешка поправка, re-extraction, confirmed
parts, оригинална inspection и VERIFIED source. И петте ledger таблици са непразни:
3 sessions, 3 sources, 5 attempts, 4 candidates, 4 decisions.
След encrypted restore целият row/column fingerprint съвпада, включително audit,
source bytes/SHA и човешката работа. Извън историческата audit граница са само
новите законни backup/restore събития, не променени стари записи.
QA ключове/бази са изолирани; production backup или секрет не е използван.

## 17. Historical compatibility

Restore и full regressions запазват 19 verified assets, 611 части, 7 kits,
84 components, 12 diagrams, 818 verified hotspots и две shared bindings.
Published ревизии/immutable request documents/source hashes остават неизменени.
Seed данните, Falch номерацията, SOURCE_REGISTER и оригиналните OEM документи не
са редактирани. Финалният diff е ограничен до parser boundary, три frontend
компонента, regressions/QA tooling и разрешени доказателства.

## 18. PARTS-DOC и официални документи

Full pytest/PG повтарят requests, kits, shared catalog bindings, immutable visual
snapshots и historical official documents. Docker CI използва exact production
image за LibreOffice read-only smoke, official visual appendix и late-bound
Builder DOCX/PDF с 80-character position. Генерирането/подписите/историческите
templates не са променяни или регенерирани върху business данни.

## 19. Security review

Проверени са fixed subprocess arguments без shell, environment allowlist без app/
DB credentials, private temp ownership, timeout/process-group cleanup, Unix AS/CPU/
file/core limits, Windows Job Object, output byte/shape guards и bounded slots.
Оригиналите/preview/evidence остават зад centralized authorization. Negative tests
покриват unauthorized actor, foreign source/candidate/part, CSRF, HMAC/actor/source/
session/version/expiry binding и stale/replay refusal. Blob lifecycle е прегледан
и поправен при late unmount response. Няма sensitive browser localStorage или
OEM текст в новите logs/artifacts. Docker OCR е network-none; няма външен OCR API.

CI dependency high/critical/unknown gates, release verifier/SBOM, authorization
inventory и Docker non-root/read-only/health checks са изпълнени. Няма нова
зависимост. Това не е външен penetration test; отделен container OS-CVE scan,
cluster-wide quota и продължителен soak не са изпълнени и не се обявяват за PASS.

## 20. Доказани и поправени дефекти

| Дефект | Преди поправката | Поправка / доказателство |
|---|---|---|
| Semaphore е per-web-process | Трети независим controller влиза при лимит 2 | OS leases + 7 regression cases; crash recovery и inherited Unix descriptor |
| Late original Blob след unmount | Нов frontend regression FAIL: нула revoke | Mounted check / immediate revoke; component PASS |
| След client disconnect + refresh липсва retry на непочната страница | Edge N=7 и component regression FAIL | Контекстен retry само на липсващия source; другите 30 реда остават |
| Невалиден worker output е необработен exception / допуска JSON list | Три нови fault cases FAIL | UTF-8/JSON object validation → sanitized 422 |
| Undo пази version от създаването | Edge отказва delete; component изпраща version 2 вместо 6 | Само успешните собствени write acknowledgements обновяват Undo; чужда version 7 продължава да отказва |

Първият hotspot helper locator беше коригиран към реалното accessible combobox
име, преди да се установи Undo дефектът. Има и коригирани QA fixture/navigation
race/typecheck грешки. Те не са представени като продуктови дефекти или PASS.

## 21. Непоправен проблем и конкретен технически план

Общото точно OEM extraction е release blocker. Не се въвежда голям parser rewrite
под прикритието на 03D. След независим review е необходим отделен ограничен
extraction hardening change със следния план:

1. Synthetic fixtures за multilevel/multilingual headers, повторени semantic column
   groups и horizontal BOM panels, без OEM Part Numbers/координати.
2. Независимо разделяне на panel regions и локални row bands; multiple description
   columns и език се разрешават чрез header/geometry evidence. Без понижаване на
   ambiguity guard, копиране на стойности или manufacturer-specific fallback.
3. Native reconstruction първо; cell OCR само за доказано нечетими локални области.
   Partial candidates запазват оригиналните клетки, bbox и човешките корекции.
4. Повторен независим exact comparator върху всички 24 страници / 611 controls,
   D13 3×30/30, occurrences/reconciliation, N-page и същите resource budgets.
5. Re-review на release matrix. Manual/CSV/mapping/transcription остават налични
   текущи механизми, но наличието им не доказва automatic OEM acceptance.

## 22. Known limitations

- Hammelmann original и P200E/X25 независими exact controls липсват.
- D13 48/38 изисква реално човешко/OEM разрешаване; D13 publication е BLOCKED.
- Малка performance извадка, няма cold-cache или дълъг soak/SLA доказателство.
- Runtime leases обхващат един container/temp namespace, не множество реплики.
- Backend CI skips: два original-protocol layout tests без LibreOffice на backend
  runner и един Windows named-mutex test на Linux. Docker LibreOffice/official
  document checks са отделни PASS, не се представят като тези два skipped tests.
- Локално Windows boundary suite: 7 PASS / 6 platform SKIP; Unix-only cases трябва
  да са успешни в Linux CI (изпълнени в product CI). Accessibility QA не е формална сертификация.
- Ограниченият extractor/PG/browser concurrency е проверен; продължителен full
  multiworker HTTP soak не е изпълняван на ограничения host.
- Official document generation е отделен Docker normal-service сценарий, не
  клик през същия synthetic browser каталог; този конкретен комбиниран сценарий е NOT RUN.

## 23. Release-readiness матрица и тестови резултати

[Machine-readable matrix](qa/catalog-builder-03d/release-readiness.json) съдържа
PASS/FAIL/BLOCKED/NOT RUN с конкретни доказателства.

| Област | Статус | Доказателство |
|---|---|---|
| D13 exact / SHA / provenance / 3×Linux | PASS | d13-linux-exact.json |
| D13 Edge / correction / refresh / no duplicates | PASS | browser-d13.json, 7 checks |
| Synthetic full publication / published reopen | PASS | browser-synthetic.json, 10 checks |
| 1/4/7, interrupted middle, single retry | PASS | browser-multipage.json |
| Hotspot lifecycle / touch / normalized geometry | PASS | synthetic browser + component regressions |
| Two tabs / autosave / source switching / LINK_EXISTING | PASS | synthetic browser |
| 5/0/5 / direct API / stale digest / fail-closed | PASS | full backend + PG suites |
| PostgreSQL / migration / encrypted ledger restore | PASS | 97 PG tests + restore rehearsal |
| Process boundary / bounded contention / no orphan | PASS | capacity/fault regressions + concurrent D13 |
| Frontend / typecheck / lint / build / translations | PASS | 618 local and CI Vitest; compiler/linter/build |
| Other real OEM exact extraction | **FAIL** | corpus-summary.json; same failure on 03C baseline |
| D13 final publication | **BLOCKED** | unresolved OEM 48/38 + unverified hotspots |
| Hammelmann / P200E/X25 exact acceptance | **NOT RUN** | missing original/control |
| Cold-cache / long soak / external security certification | **NOT RUN** | explicitly outside measured evidence |

Full CI `38210276450` on `abbc689`: backend 1216 PASS / 3 SKIP / 96 PG deselected,
frontend 616 PASS, PG 96 PASS, Docker PASS. CI `38213529031` on `4982f19`: frontend
618 PASS (65.19 s), PG 97 PASS (616.14 s), Docker PASS, backend 1217 PASS / 3 SKIP /
97 PG deselected (1361.66 s). [CI evidence](qa/catalog-builder-03d/ci.json) записва
точните scope/команди/skips. Двата допълнителни comparator regressions и по-строгите
schema assertions са изпълнени локално; финалният PR-head CI е отделна задължителна проверка.
Latest authoritative jobs are [PR checks](https://github.com/djebedaq/AssetCore/pull/104/checks).
A green check confirms its test scope, not the failed OEM corpus acceptance.

Local frontend: 66 files / 618 PASS / 216.09 s; target hotspot 5 PASS / 3.60 s.
Typecheck/lint PASS; build PASS / 4.88 s with existing large-chunk advisory.
Final local boundary/comparator pytest: 7 PASS / 6 Windows platform SKIP / 6.20 s.
Full Ruff, protected migration validator and authorization inventory PASS.
Interrupted attempts and all skips are retained in the report, not counted as PASS.

## 24. Препоръка

**NO-GO за бъдещо общо production внедряване.** Security/publication/durability
проверките и D13 са успешни; corpus automatic acceptance е възпроизводим FAIL.
PR предоставя reviewable fixes и честно приемателно доказателство, но остава
изрично NOT READY. След независим review потребителят решава последващия
ограничен extraction scope. Няма автоматично продължаване или deployment.

## 25. Възпроизводими команди

Изпълняват се само в development/нови QA ресурси. Full CI използва repository
`.github/workflows/check.yml`; Node CLI еквивалентите локално са необходими, защото
pnpm CLI не е наличен на host-а.

```powershell
.venv/Scripts/python.exe -m ruff check backend/app backend/alembic backend/scripts scripts tests
.venv/Scripts/python.exe backend/scripts/validate_migration_history.py --require-all-protected
.venv/Scripts/python.exe backend/scripts/validate_authorization_inventory.py
.venv/Scripts/python.exe -m pytest -q tests/test_catalog_final_qa.py tests/test_catalog_final_faults.py tests/test_catalog_process_capacity.py --tb=short
node frontend/node_modules/vitest/vitest.mjs run --root frontend --maxWorkers=1
Push-Location frontend
node node_modules/typescript/bin/tsc -b --pretty false
node node_modules/eslint/bin/eslint.js src --max-warnings 0
node node_modules/vite/bin/vite.js build
Pop-Location
.venv/Scripts/python.exe tests/browser/run_catalog_final_acceptance_qa.py synthetic
.venv/Scripts/python.exe tests/browser/run_catalog_final_acceptance_qa.py multipage
.venv/Scripts/python.exe tests/browser/run_catalog_final_acceptance_qa.py d13 --pdf <local-original.pdf> --expected <local-control.json>
```

Browser launcher създава нова SQLite QA база, случайни in-memory credentials и
loopback server; PLAYWRIGHT_MODULE сочи локалната Playwright инсталация. Expected
се предоставя само на comparator/browser process, не app server. За Windows OCR
се използват разрешените local Tesseract CLI/models, не QA wheel в production.

Linux recipe: production-oriented QA image, `docker run --rm --init --read-only
--network none --memory 1g --cpus 2 --pids-limit 64 --tmpfs /tmp:rw,nosuid,size=192m`.
Mount само original PDF read-only, QA script и private output directory. Изпълни:

```text
python scripts/catalog_adaptive_pdf_qa.py extract /qa-original.pdf --pages 13,15 --runs 3 --output /qa-output/d13-extraction.json
python scripts/catalog_adaptive_pdf_qa.py concurrency /qa-original.pdf --page 13 --output /qa-output/concurrent.json
# Separate host process AFTER extraction; expected is never a container input:
python scripts/catalog_adaptive_pdf_qa.py compare <private-report.json> <local-control.json> --output <aggregate-proof.json>
python scripts/catalog_final_corpus_qa.py extract --output <private-corpus-report.json>
python scripts/catalog_final_corpus_qa.py compare --report <private-corpus-report.json> --output <aggregate-corpus-proof.json>
```

Corpus recipe монтира само разрешената technical library и QA scripts. Повтори с
03C QA image за baseline; сравнявай hashes, payload/provenance и quality, изключвай
timings при equality check. Private extraction reports съдържат OEM редове и
остават ignored. Linux full backend е `python -m pytest -q -m "not postgres"
--durations=10`; PG concurrency и encrypted backup/restore командите са точните
съществуващи workflow steps, с newly-created QA databases/keys.

## 26. Бъдещ deployment / rollback план — НЕ Е ИЗПЪЛНЯВАН

1. Отстрани corpus blocker, повтори exact acceptance, независим review и изрично
   разрешение за merge. Фиксирай release SHA, image digest, SBOM и release artifacts.
   Провери required migration head 0033 и compatibility без downgrade.
2. Deployment е отделна разрешена задача. Тогава операторът проверява production
   runtime/resources/toolchain и прави проверен encrypted backup с доказано restore
   върху отделна QA база. Настоящият етап няма production конфигурационен достъп.
3. Maintenance/traffic plan, текущ image digest и rollback image се записват преди
   контролирана смяна. 03D няма нова migration; не се регенерират signed documents,
   snapshots или durable решения. Миграционен failure прекратява внедряването.
4. Smoke: liveness/readiness, login/четирите роли, verified assets и shared refs,
   исторически DOCX/PDF и requests, source inspection, native/OCR, correction/resume,
   busy/timeout, wrong-role/direct-publish refusal и точни source fingerprints.
5. Abort при integrity drift, unauthorized original/evidence, lost correction,
   orphan subprocess, unbounded resource use, unhealthy runtime или gate bypass.
   Няма GO само въз основа на HTTP 200/пълен брой OCR редове.
6. Rollback: предходен 03C image със запазена 0033 база/ledger/audit, след проверка
   на image/schema compatibility. Предходният image няма shared parser leases:
   временно един web worker и проверен cgroup/parser budget са задължителни условия
   за такъв rollback. Никога image преди 03A или lossy Alembic downgrade.
7. Ако има доказано data corruption, спри writes и направи отделен incident/restore
   план с одобрение и съхранение на всички по-нови human decisions. Не замествай
   автоматично базата с по-стар backup и не изтривай review/evidence.

Всички собствени run-контейнери са `--rm`; локалният PG container/volumes се
премахват само по собствения случаен name във finally. QA evidence/оригиналите
остават запазени. Няма production операции, merge или deployment.
