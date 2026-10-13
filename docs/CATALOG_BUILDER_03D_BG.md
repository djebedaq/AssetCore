# CATALOG BUILDER 03D FINAL — интеграция и окончателно приемане

## Final worker evidence boundary fix — 12.10.2026

Независимият review на `07b0360` откри структурен пропуск във вложените worker
данни. Реалният subprocess regression възпроизведе приемане на `rows: [{}]`;
HTTP тестовете доказаха 500 при невалиден row/payload и 200 при невалидна
table/quality структура. Началният целеви набор даде **5 FAIL / 1 PASS**.

`process.valid_evidence()` вече използва малък вътрешен structural contract в
`evidence.py`, преди резултатът да стигне до ledger. Проверяват се payload,
warnings, schema/mapping, raw cells, boxes, таблици/row bands, quality, words,
provenance и употребяваните optional geometry полета. Нечислови/неограничени
числа, bool вместо index и прекалено дълбок JSON се отказват контролирано.
Няма нормализиране, изхвърляне на частични редове или извеждане на липсващи части.
Празните идентификатори, nullable description/quantity и оригиналният quantity_raw
остават допустими **непотвърдени** кандидати с непроменени raw доказателства.

Невалидният worker output връща sanitized **422**, опитът и източникът стават
**FAILED**, а не SUCCEEDED или stranded RUNNING. Предишният успешен evidence,
човешката поправка и candidate IDs се запазват; незабавен retry работи. Добавен е
отделен реален PostgreSQL regression за същата транзакционна последователност.
Действащият deadline recovery механизъм при прекъсване остава непроменен.

Локално: **83/83** нови contract/HTTP теста; по-широкият първи набор е
**179 PASS / 8 Windows POSIX SKIP**, преди последното разширяване на новите тестове.
Окончателният локален worker/fault набор е **96 PASS / 6 POSIX SKIP** за 48.22 s.
Всички worker/fault проверки са повторени; окончателните пълни backend,
frontend, PostgreSQL, Docker и security резултати са в
[CI на окончателния PR HEAD](https://github.com/djebedaq/AssetCore/pull/104/checks).

Повторното независимо Linux приемане върху текущите source hashes е
**611/611 от 24 OEM страници** и **D13 3 × (20/20 + 10/10)**; два едновременни
D13 OCR worker-а също дават 20/20 всеки. Контролите са недостъпни при extraction
и се четат само от отделния comparator след записването на резултатите.
[Нови агрегирани доказателства](qa/catalog-builder-03d/final/worker-boundary-fix/implementation.json),
[OEM](qa/catalog-builder-03d/final/worker-boundary-fix/corpus.json),
[D13](qa/catalog-builder-03d/final/worker-boundary-fix/d13-linux-exact.json),
[regressions](qa/catalog-builder-03d/final/worker-boundary-fix/regressions.json).

Оценката остава ограничен, контролиран GO след успешен финален CI и независим
review. Матрицата вече има **22 PASS / 1 BLOCKED / 5 NOT RUN**. Старите измервания
и NO-GO историята са запазени. Няма промяна на OCR алгоритъм, DB/миграции,
resource limits, canonical capacity, fingerprints, versions, reconciliation,
inspection receipts, audit, permissions или publication gate. D13 остава
непубликуван и 48/38 не е разрешено. Production не е достъпвана.

## Текуща оценка и обхват

**Препоръка: GO за ограничен, контролиран release scope след независим review,
успешен CI на окончателния HEAD и отделно разрешение за внедряване.** PR #104
остава **Draft, неслят**. Това не е разрешение за merge или deployment.

Core приемането включва шестстъпковия процес, durable ledger, човешки поправки,
publication gate, authorization, SQLite/PostgreSQL, encrypted restore, официални
документи и ограничено локално OCR изпълнение. Автоматичната exact точност е
доказана за осемте Falch/HYDWIN каталога и D13 по-долу. Няма твърдение за
универсална точност за непознати OEM оформления.

Актуалните доказателства са във [final/](qa/catalog-builder-03d/final/README.md) и
[readiness матрицата](qa/catalog-builder-03d/release-readiness.json).
Старите 03D измервания и първоначалният NO-GO са запазени под историческия раздел
по-долу и в оригиналните QA файлове. Те не са текущи измервания на комбинирания код.

## Git интеграция

- Потвърден `origin/main`: `0c6101d624bbc06553b6a047060ca5c4c91f9128`, merge на #105.
- Начален #104 HEAD: `0dec19a37ac08ed78f938400503207dd76d97dc5`.
- Локална backup reference: `backup/catalog-builder-03d-before-03e-integration`.
- Безопасен merge в съществуващия branch: `6b84483d1e36e72494d8c6b24e71b5bdea7df073`.
- Единственият конфликт беше коментар в `process.py`; няма автоматично ours/theirs
  разрешаване, reset/clean, rebase или force push.
- Последна продуктова поправка: `cb4e4a32f450aff5ef7609b5562a430fc92b53b5`.
  След нея се променят само QA/документация; [module hashes](qa/catalog-builder-03d/final/implementation.json)
  свързват Linux измерванията с актуалния код.

`capacity.py` и тестовете му съвпадат с main. Има един каноничен OS lease механизъм;
локалният предварителен semaphore е част от същата process boundary. Native-grid,
native tables и OCR използват `process.extract`, същите slots и същите бюджети.
Не са пренасяни паралелни capacity реализации. #105 не е променян.

## Четирите запазени поправки

| Поправка | Актуално доказателство |
|---|---|
| Late original response след unmount освобождава Blob URL | Component regression и реален Edge: задържан авторизиран response, navigation, release след unmount и наблюдаван revoke |
| Retry на непочната страница след прекъсване | Edge N=7: шест успешни източника/30 кандидата остават; refresh и retry само на липсващата страница дават 35 отделни IDs |
| Malformed worker UTF-8/JSON/shape се отказва контролирано | Шест real-subprocess fault случая; sanitized 422, без native exception/details |
| Undo следва собствената последна acknowledged version | Component и Edge: place/move/resize/verify/unverify/Undo; чуждата stale версия продължава да връща 409 |

При final audit беше доказан още един случай в третата поправка: `{}` и
`{"rows": {}}` минаваха първоначалната object проверка. Новите тестове първо дадоха
**2 FAIL / 3 PASS**. Worker envelope вече проверява типовете на необходимите полета
и контролирани error codes преди consumer access; включено е и невалидно `error: []`.
Локално: **6 PASS / 1 Windows POSIX SKIP**. Алгоритъмът, review решенията,
fingerprints, версии, inspection receipts и publication gate не са променени.

## Реални OEM каталози: ново Linux приемане

Независимо извличане → private записан резултат → отделен comparator. Verified
JSON контролите са скрити чрез read-only tmpfs в extraction контейнерите; D13
expected JSON не е монтиран. Няма oracle стойности в extractor-а.

| Каталог | Страници | Точни записи | Липсващи / допълнителни |
|---|---:|---:|---:|
| Falch 1000 drive pump | 2 | 34/34 | 0/0 |
| Falch 1000 liquid part | 2 | 46/46 | 0/0 |
| Falch 1000 wheel jet | 6 | 164/164 | 0/0 |
| Falch 500 pump | 3 | 65/65 | 0/0 |
| Falch 500 unloader valve | 3 | 65/65 | 0/0 |
| Falch 500 valve 500bar | 2 | 32/32 | 0/0 |
| Falch 500 wheel jet | 5 | 147/147 | 0/0 |
| HYDWIN Fussen plunger pump | 1 | 58/58 | 0/0 |
| **Общо** | **24** | **611/611** | **0/0** |

Проверени са position, Part Number, exact оригинално описание, quantity и
quantity_raw, както и source SHA/physical page/multiplicity. Comparator отказва
пропуснати/дублирани каталози или страници и подменен SHA. Няма измислени части,
загубени leading zeros или слети физически occurrences.

Трите празни Part Numbers и едното ненумерично количество на Fussen са запазени.
Тези непълни кандидати остават за човешки review. **611 exact source records не
означава 611 валидни или VERIFIED части.** Нито OCR success, нито броят редове
одобрява източника. [Per-page comparison](qa/catalog-builder-03d/final/corpus-comparison.json),
[summary и 03C сравнение](qa/catalog-builder-03d/final/corpus-summary.json).
Първоначалният 03C резултат остава 0/611 exact; поправката е merged #105,
а настоящият PR доказва съвместната ѝ работа с четирите reliability поправки.

## D13: Linux и реален Edge

Original SHA `e9540c2af79802d000f186381c403dfbca6ae6b58ecb6cb13b9ecec862558e42`;
схема 12, списъци 13/15, `TCD13A.01 Chassis Assembly-2`.
Три нови Linux повторения: **3 × (20/20 + 10/10)**, всички exact полета и provenance,
нула допълнителни редове или останали descendants.
[Linux exact](qa/catalog-builder-03d/final/d13-linux-exact.json).

Edge премина 7 проверки: едно разпознаване/една обща таблица, 20+10 exact source
occurrences, 390/768/1440 и keyboard, human correction/refresh/възстановяване на
оригинала, re-extraction със същите IDs и без дубликати, durable source review,
server blockers и оригиналната схема. [Browser D13](qa/catalog-builder-03d/final/browser-d13.json).
QA review се упражнява само с временен QA actor/база; няма бизнес одобрение.
Callout 48 / списъчна позиция 38 остава нерешен OEM въпрос. **D13 не е публикуван**,
няма фабрикувани markers или подмяна на оригинални номера.

## Browser, lifecycle и N-page интеграция

Synthetic normal UI/API: създаване → PDF → extraction → поправки → confirmation →
source review → touch hotspots → readiness → публикация → read-only reopen.
**11 PASS**, нула page errors. Проверени са две действителни browser tabs,
stale autosave/confirmation, logout/login, BG/EN/RU, focus trap/Escape/keyboard,
source-switch cancel/accept и reason/manual/link isolation. Failed inspection
премахва стария оригинал и блокира review; late response след unmount освобождава
Blob URL; reopening изисква нова inspection.

Hotspots: point/rectangle, move/resize, Undo/delete, multiple occurrences/схеми,
verify/unverify, 409 stale version, pointer cancellation, zoom/pan и normalized
geometry при touch/390/768/1440. След publication всички original assignments,
части, coverage и hotspot records съвпадат точно с pre-publication graph.
[Synthetic browser](qa/catalog-builder-03d/final/browser-synthetic.json).

N-page Edge: **1 → 5**, **4 → 20**, **7 → 35** кандидата; N=7 включва прекъснат
middle request, refresh и single-source retry. Нула auto-VERIFIED, един успешен
attempt на source. Backend/PG покриват и 2/3, различни документи, несъседни
страници, съвместим/несъвместим контекст и second pass към по-ранна страница.
[N-page browser](qa/catalog-builder-03d/final/browser-multipage.json).

Screenshots са реални, само synthetic: [390 parts](qa/catalog-builder-03d/final/screenshots/parts-390.png),
[768 touch](qa/catalog-builder-03d/final/screenshots/touch-hotspots-768.png),
[rectangle](qa/catalog-builder-03d/final/screenshots/rectangle-second-scheme-1440.png),
[published reopen](qa/catalog-builder-03d/final/screenshots/published-reopened-1440.png).
Няма OEM PDF/страници/crops/редове, credentials или production данни в новите artifacts.

## Concurrency, fault injection и ресурси

Новият Linux live тест стартира **три независими controllers**, два заемат OS slots
и изпълняват реален D13 OCR; третият получава busy за ~0.00034 s при извикването.
Двата OCR резултата са independently exact 20/20. Отделно е SIGKILL-нат точният
собствен worker при активен Tesseract: controlled 422, нула OCR orphans, следващ
native parse използва същия освободен slot и е exact 10/10.
[Live capacity/crash proof](qa/catalog-builder-03d/final/live-capacity-exact.json).
Не е симулирано успешно OCR чрез готови части в DB.

Runtime budget: **2 CPU / 1 GiB / 64 PID / 192 MiB tmpfs**, non-root/read-only,
network-none, worker 45 s / 1 GiB AS. Лимитите не са увеличени.

| Измерване | Нов резултат |
|---|---|
| 24 native OEM страници, median | 2.5818 s, без тежък OCR |
| D13 13, три fresh workers | 5.0543 / 4.3956 / 4.3454 s; max sampled tree RSS 348.49 MiB |
| D13 15 native | 0.7808 / 0.8835 / 0.7277 s; max sampled tree RSS 172.91 MiB |
| Два concurrent OCR workers | 4.9702 s общо; sampled CPU 8.74 s; sampled tree RSS 600.79 MiB |
| Concurrent cgroup peak | 551825408 bytes (~526 MiB); peak PID/thread count 13; нула OOM/max events |

RSS sampling е на 20 ms и сумата брои shared pages повече от веднъж; container
memory.peak е отделна мярка. OS cache не е reset-ван; няма certified cold boot,
надежден production P95 или дълъг soak. Спрямо 03E няма доказана съществена
регресия; малките разлики са в натоварена 8 GiB development машина.
[Performance](qa/catalog-builder-03d/final/performance.json).

## Backend, PostgreSQL, история и security

Publication остава authoritative/fail-closed. Full suites повтарят 5/0/5:
непроверен source 2, COMPLETE/readiness отказ, direct publish 409, нула нови
published revisions. Fingerprint/assignment/mapping/part/review промяна,
PENDING/CONFLICT, неподходяща роля, legacy draft и stale digest остават blockers.
PG overlapping transactions включват publish/edit, group processing/review,
assignment/review и двама отделни actors с actor-bound receipts/audit.

Няма нова DB схема/migration. Protected history е 33 migrations, head 0033;
constraints/indexes/FK assertions се изпълняват на SQLite и PG. Encrypted QA restore
сравнява всички historical rows/columns, original bytes/SHA, audit и човешки решения.
Ledger counts: 3 sessions, 3 sources, 5 attempts, 4 candidates, 4 decisions.
Запазени anchors: 19 verified assets, 611 части, 7 kits, 84 components, 12 diagrams,
818 hotspots и 2 shared bindings. PARTS-DOC/snapshots/официални DOCX/PDF остават
immutable; LibreOffice и normal-service document generation са отделни Docker checks.

Повторен е review на native_grid/panels/schema/quality/extraction/service/capacity/
process: bounded 12000 segments/24000 cells/80 signatures/ограничени partitions,
неясните schema/coverage остават review, fixed argv/no shell, env allowlist,
private temp/lease files, process-group cleanup, HMAC/actor/version/expiry binding,
централизирани permissions, authorized originals/evidence и Blob lifecycle.
Няма cloud OCR, нови зависимости/роли/permissions, промени в verified controls,
inventory/Falch номерация, source register, OEM оригинали или historical artifacts.
[Security и regressions](qa/catalog-builder-03d/final/security.json).

## Проверки, първоначални неуспехи и ограничения

Combined CI `38245128678` (`1040a41`): **1247 backend PASS / 3 SKIP / 97 PG deselected**
за 1394.28 s; отделен config gate 17 PASS; **97 PostgreSQL PASS** за 569.86 s;
**618 Vitest PASS / 66 files** за 55.11 s; всички Docker/image/document/restore
jobs PASS. Последващият окончателен HEAD променя QA/документация и се проверява
отново изцяло; точните финални counts са в PR checks/предаването.

Точните CI резултати са в [final CI](qa/catalog-builder-03d/final/ci.json), а
проверките на окончателния HEAD са авторитетни в [PR #104 checks](https://github.com/djebedaq/AssetCore/pull/104/checks).
Локално: typecheck/lint/build/Ruff/protected migrations/authorization PASS;
29 targeted frontend PASS; 35 backend targets PASS/6 POSIX SKIP, след което
final malformed suite 6 PASS/1 POSIX SKIP. Linux CI изпълнява POSIX случаите.

Честно отчетени начални опити:

- Новите worker-shape regressions първо FAIL, после поправени; assertions са запазени.
- Локален unrestricted Vitest е INTERRUPTED; повторен bounded target 29/29 PASS.
- Локален image rebuild е INTERRUPTED при бавни package installs/малък host RAM резерв.
  Linux приемането използва проверения production-oriented image плюс текущ read-only
  backend bind/hashes. Exact commit production image build и runtime/document smokes
  се изпълняват отделно в GitHub Docker CI.
- Първият combined CI `38244352117`: backend/frontend/PG PASS, Docker FAIL в isolated
  Compose stage `post_deploy_smoke`, без достатъчно assertion detail. Няма доказана
  възпроизводима продуктова причина. Добавена е sanitized exception type/function/line
  QA диагностика; повторението `38245128678` премина Compose без промяна на assertions
  или deployment логиката. Окончателният CI трябва също да е зелен.
- Първият synthetic Edge опит FAIL при pan assertion. QA drag вече използва видимото
  пресичане с viewport и изчаква zoom overflow; product pan/CSS не са променяни и
  assertion-ът не е отслабен. Повторението премина 11/11.

NOT RUN: Hammelmann без original/control; P200E/X25 без independent control;
непознати OEM оформления; дълъг soak/certified cold-cache benchmark;
external penetration/screen-reader certification и отделен OS-CVE scan.
Parser quota е за един runtime/shared temp namespace, не cluster-wide quota.
Official document generation от същия browser synthetic каталог не е изпълнено;
нормалният document renderer/история са проверени отделно чрез Docker/PG.
Тези непроверени възможности са извън препоръчания ограничен release scope.

## Възпроизводимост и бъдещ rollout/rollback — НЕ Е ИЗПЪЛНЯВАН

Командите са в [final QA README](qa/catalog-builder-03d/final/README.md) и съществуващия
`.github/workflows/check.yml`. Originals/expected/raw OEM outputs остават локални.

1. Независим review; explicit merge approval; фиксирани release SHA/image digest/SBOM,
   всички exact-HEAD CI jobs успешни. Production compatibility се проверява в отделна
   разрешена задача; настоящият етап не инспектира production.
2. При бъдещо разрешение: проверен encrypted backup и QA restore; image/toolchain и
   наличен migration head 0033; maintenance/abort план преди writes. Не се генерират
   наново historical signed documents или snapshots.
3. Контролиран image switch, readiness/liveness/login/roles; verified inventory,
   shared refs/kits/PARTS-DOC/исторически документи; source review/native/OCR,
   correction/resume, direct-publish refusal и bounded capacity smoke.
4. Abort при integrity drift, authorization leak, lost human edit, orphan OCR,
   unhealthy runtime или publication bypass. Не се увеличават limits за маскиране.
5. Rollback image кандидат е merged 03E `0c6101d` със запазена 0033 база и ledger:
   schema/extractor version са съвместими, OS leases вече са налични. Връщат се четирите
   известни frontend/fault-handling ограничения; оценяват се преди fallback и при нужда
   се спира новото authoring/OCR. Няма DB downgrade или изтриване на review/evidence.
6. При data corruption: спиране на writes и отделен одобрен incident/restore план,
   който съхранява всички по-нови human decisions/audit; не се заменя автоматично базата
   със стар backup.

Всички нови QA run контейнери са `--rm`; собствените loopback servers/browser contexts
се затварят във finally. OEM/untracked/QA материали са запазени. **Production не е
достъпвана; няма merge, deployment или премахване на Draft статуса.**

---

## Исторически 03D отчет — преди интеграцията на #105

Следващият текст е запазен като историческо доказателство за първоначалната 03C
база. Неговите NO-GO/FAIL/CI/performance стойности не описват настоящия combined build.


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
