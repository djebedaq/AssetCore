# CATALOG BUILDER 03B — Adaptive PDF Extraction

Начална база: `becc09f3715dbd66780779b33e9e2b834f28ff74` (`origin/main`, merged PR #101).
Обхват: extractor, използване на durable review от 03A и минимална интеграция на съществуващия бутон за извличане. Последователността Каталог → Референция → PDF страници → Части → Маркери → Публикуване е запазена.

## 1. Архитектура

`extraction.py` управлява независими предложения и избира по семантика, валидност на клетките, покритие и геометрия. Версия: `ADAPTIVE_PDF_2`; durable attempt extractor: `SPARE_PARTS_2`. Непразна таблица или голям брой кандидати сами по себе си не означават успешна обработка.

Модули: `tables` — native таблици/думи; `quality` — сравнение и покритие; `raster`/`raster_geometry` — композиция, grid и трансформации; `cell_ocr` — ограничен CLI adapter; `region_ocr` — fallback за borderless сканове; `context` — семантични профили между избраните източници. Не се добавят сървъри, queues, Redis или Celery.

## 2. Независими стратегии

| Стратегия | Поведение |
|---|---|
| `NATIVE_TABLE` | PyMuPDF `find_tables()` и оригинални клетки/row bands. |
| `NATIVE_LAYOUT` | Независим анализ на PDF думи и локална геометрия, независимо от успеха на `find_tables()`. |
| `IMAGE_CELL_OCR` | Оригинални растерни изображения, physical grid, отделни клетки, управляем Tesseract. |
| `OCR_REGION_LAYOUT` | Локален CLI OCR и реконструкция по думите за borderless/broken-grid изображения. |
| `OCR_LAYOUT` | Съществуващият bounded embedded OCR като последен fallback. |

Metadata таблици без BOM семантика се отхвърлят с диагностична причина. Невалидна native таблица не скрива работещото независимо layout предложение. Несъвместима actual grid геометрия не заема старите координати чрез word fallback.

## 3. Автоматичен избор и покритие

`quality.assessment` сравнява наблюдавани редове, покрити source indices, липсващи редове, непълни клетки, семантични колони и геометрия. `COMPLETE_CANDIDATES` е технически резултат, **никога човешко VERIFIED**.

При ruled tables основата е `PHYSICAL_ROW_BANDS`; при borderless — `TEXT_LINE_REGIONS` с `BORDERLESS_COVERAGE_UNCERTAIN`. За borderless не се твърди независимо доказан брой видими физически редове. Пропуски в числовите позиции не са completeness сигнал.

Не се стартира тежък OCR при надеждно native извличане. Непокрита значителна image област, повреден native текст или липса на полезен текст активират OCR. Native остров не може да прикрие непрочетена растерна област: резултатът получава `RASTER_COVERAGE_UNRESOLVED` и изисква review.

Различни предложения за една област се запазват като competing readings и `STRATEGY_DISAGREEMENT`. По-чисто предложение не изхвърля непокрити частични редове от другата стратегия. Дублираните области с еднакви стойности се отчитат веднъж; отделни видими редове с еднакви стойности остават отделни кандидати. Сравнението не променя входните предложения между pass-овете.

Физическите row bands се проверяват независимо и когато техните колони са неразчетени. Един кандидат покрива най-много един band. 16 кандидата при 20 открити bands водят до липсващи редове и `NEEDS_REVIEW`; raw таблицата остава достъпна за mapping. Coverage анализът има отделна граница 2000 bands; достигането ѝ се отчита като непълно покритие.

## 4. Image grid и cell OCR

Оригиналната растерна резолюция се използва в рамките на pixel budget. Pillow threshold/closing и ограничено откриване на дълги хоризонтални/вертикални линии определят действителните row/column bands. Page frame не се приема автоматично за таблица. При липса на използваемо embedded изображение се рендерира ограничена PDF страница.

Сравняват се ориентации 0/90/180/270 чрез локалните заглавия. Малък наклон се търси на намалено изображение до ±3°, с максимум три full-resolution предложения. Клетките имат inset срещу grid линиите и бял padding. Pixel → original PDF трансформациите, original resolution, mask, grid, row boxes и OCR word boxes се пазят в evidence.

Няма OpenCV/NumPy runtime dependency, manufacturer coordinates, фиксирани Part Numbers или очаквани бройки в продуктовия код.

## 5. Tesseract adapter

Съществуващият Linux image вече съдържа Tesseract CLI и eng/deu/bul/rus модели. Няма нова production зависимост и няма Windows QA wheel в продуктовия pipeline.

Клетките се подават като private PNG list към един CLI процес за batch. Използват се фиксирани аргументи, `shell=False`, OEM 1 и TSV output чрез `tessedit_create_tsv=1`. Техническите идентификатори се четат с английски модел; езикът за описанията може да се избере от локалните заглавия. Не се комбинират четири езика за Part Number.

Един ред използва PSM7; измерени многострочни клетки — PSM6. Езикът на описанията се определя от локалните семантични заглавия, независимо кой модел е успял да ги прочете: английски прочит на „Benennung/Menge“ избира немски модел за описанието. До 24 празни/нискоуверени клетки имат един selective autocontrast retry. Различните прочити остават evidence; няма O/0, I/1, кирилица/латиница или пунктуационни подмени. Confidence е помощен сигнал.

Ограничения: 512 клетки, 4 MiB TSV, до 35 s за CLI batch в общия page deadline; максимум 8 image области в aggregate pixel budget. Cell words, включително запазените алтернативни прочити, спазват същия page word budget като native стратегията. `OMP_THREAD_LIMIT=1`. OCR/DPI/PSM/езици не са нови UI настройки.

## 6. Transparency masks

SMask се декодира след проверка на размерите, композира се с базовия Pixmap и после върху бял фон. Несъвместими mask размери не се използват. CMYK се преобразува към RGB. Page rendering запазва композицията на PDF renderer-а. Synthetic alpha case и реалният D13 masked image са проверени в Linux.

## 7. Group-aware N източника

Съществуващият endpoint остава съвместим. `ExtractSelection` има additive `expected_version`, `group_context`, `context_only`.

Съществуващият UI бутон изпълнява първи pass за всички текущо избрани списъци в определения ред. След него само страниците с `quality.needs_context` получават втори pass. Сървърът създава максимум 8 bounded профила от успешните актуални sibling attempts на същата extraction session и проверява evidence digest.

Профилите съдържат семантични заглавия, mapping и относителни ширини, без клетъчни стойности и абсолютни координати. Локалните клетки и локалната геометрия трябва да са съвместими. Надежден native профил от същата страница също може да помогне на raster таблица с нечетими заглавия. Headerless borrowing между различни PDF-и е забранено; чужд документ изисква поне две локални семантични съвпадения. Конфликтни mappings не се прилагат.

Проверени са 1/2/3/4/7 списъка и по-късна успешна страница, която помага на по-ранни списъци. Няма правило „точно две“. Неуспешна страница не спира следващите; retry използва текущия durable context. Няма DB транзакция през целия OCR.

## 8. Интеграция с 03A

Не се добавят DB таблици/колони/миграции. Използват се съществуващите sessions, sources, attempts, candidates и review decisions от 0033. Историята на опитите, audit, actor-bound HMAC preview и source fingerprints остават authoritative.

Artifact bytes се проверяват срещу записания SHA-256 преди worker-а; worker-ът независимо изчислява SHA-256 и записва физическата страница/версия във всеки кандидат. Mapping запазва provenance и оригиналния extraction method. Стар attempt не се преетикетира като нов extractor при възобновяване.

## 9. Човешки корекции и кандидатна идентичност

Уникалните оригинални payload-и запазват съществуващата stable identity без bbox dependence. За отделни еднакви видими редове се добавя occurrence key от локалния table/row index. Съществуващите unique constraints не се премахват. Повторена еднаква позиция/Part Number получава отделна reconciliation задача: няма автоматично сливане; операторът може изрично и с audit причина да свърже оригиналните occurrences към съществуваща част. И двете оригинални геометрии/кандидати остават записани.

Повторно извличане не презаписва `candidate.values` или потвърдена част. Различен OCR номер за поправен ред води до reconciliation конфликт. Променен набор от occurrence identities след човешка работа създава `OCCURRENCE_SET_CHANGED`, включително при същия брой редове, но изместени table/row ordinals. Поправката остава записана, но двусмисленото прехвърляне към друг еднакъв ред изисква reconciliation. Оригиналните клетки и всички attempts остават достъпни.

## 10. Частични резултати

Физически открит ред с празна/нечетима позиция, номер, описание или количество остава кандидат, включително празен physical band. Невалидни стойности не стават потвърдена част без поправка. Пазят се `raw_cells`, `raw_values`, source indices, warnings и геометрия.

Неправдоподобно количество, mixed-script/whitespace identifier, OCR disagreement и непокрит ред са конкретни review сигнали. Ако следваща raster област прекъсне, завършените области се запазват с incomplete warning. При page worker timeout се запазват предишните durable резултати и успешните други страници; неизпратени вътрешни резултати от убития worker не се представят като завършен attempt.

Incomplete quality изисква original inspection и изрична manual completeness/transcription атестация при source review, освен разрешаване на всички кандидати. Нулев/неуспешен източник продължава да блокира публикацията. „Успешен extractor“ не е VERIFIED.

## 11. Реален D13 — Windows

Оригинален SHA-256: `e9540c2af79802d000f186381c403dfbca6ae6b58ecb6cb13b9ecec862558e42`. Физически страници 13 и 15; схема 12 е запазена отделно.

Три Windows CLI изпълнения: 20/20 + 10/10, точно съвпадение на позиция, Part Number, оригинално описание и количество, SHA-256 и physical page. Използван е QA-only portable upstream Tesseract 5.5.3.20260724, извлечен от официален release installer след SHA-256 проверка срещу публикувания release asset digest. Installer не е изпълняван и системна инсталация не е променяна.

Изпълнен е реален Edge сценарий през нормалния UI: upload оригинала → схема 12 → списъци 13/15 → еднократно извличане → exact comparator → draft edit/refresh → confirmation → re-extraction без дубликати → original inspection/review → refresh. Няма page errors. Контролният JSON е достъпен само за отделния comparator след извличането, не за app server/worker.

## 12. Реален D13 — Linux Docker

Използван е production Dockerfile, non-root Linux runtime, без мрежа, read-only filesystem, 1 GiB container memory, 2 CPU, 64 PID и private 192 MiB tmpfs. Оригиналният PDF е read-only QA mount. Expected JSON **не е монтиран** в extraction контейнера; сравняването е отделен последващ host процес.

Три повторения: страница 13 — **20/20**, страница 15 — **10/10**. Runtime/model fingerprints, exact-field counters и resource measurements са в `docs/qa/catalog-builder-03b/`. Не са включени OEM PDF, оригинални crops или списък с OEM части в PR.

## 13. Exact-field accuracy

| Физическа страница | Позиция | Part Number | Оригинално описание | Количество | Source SHA/page |
|---|---:|---:|---:|---:|---|
| 13 | 20/20 | 20/20 | 20/20 | 20/20 | Проверени |
| 15 | 10/10 | 10/10 | 10/10 | 10/10 | Проверени |

Контролният JSON е независим post-extraction QA контрол. Няма вход/достъп до него от алгоритъма. Сравняват се редове и четирите полета, а не само броят.

## 14. Ресурси и performance

Началният Linux benchmark измери image page 13: wall 3.14–4.65 s, sampled CPU 2.95–3.09 s, peak process-tree RSS 305.82–446.46 MiB; native page 15: wall 0.73 s, CPU 0.59–0.60 s, RSS 171.50–172.19 MiB. Максимум 3 процеса включително QA controller за cell OCR и 2 за native. Windows warm image runs: 3.05–3.25 s; cold run 14.92 s при паралелно локално QA натоварване. Това са измервания, не SLA.

Финалните машинночетими отчети съдържат измерванията за точния Linux image и implementation hashes. Sampling е 20 ms, process-tree RSS включва controller-а; кратки пикове между пробите може да не се уловят. Queue wait е 0: съществуващият semaphore връща busy при зает слот, без неограничена опашка.

Финален Linux image след cleanup/identity/word-budget корекциите: Tesseract 5.5.0, PyMuPDF 1.26.7, Pillow 12.3.0, Python 3.12.15. За трите точни повторения page 13: wall 3.55–3.84 s, CPU 3.54–3.68 s, RSS 350.16–351.45 MiB; native page 15: wall 0.57–0.57 s, CPU 0.54–0.56 s, RSS 173.96–174.88 MiB, без OCR. Windows: image wall 3.59–8.36 s, native wall 0.42–0.97 s. Предходен Linux image опит при силно паралелно host QA натоварване достигна 42.03 s, близо до 45 s deadline; това остава отчетено, без latency SLA.

Два едновременни Linux worker-а в общ 1 GiB / 2 CPU контейнер върху финалния код: два точни резултата 20/20, aggregate wall 4.04 s, CPU 7.48 s, peak tree RSS 604.85 MiB, максимум 5 процеса включително controller, 0 останали descendants. Измервателят обхваща children на всички spawning threads. Начален опит едновременно с други Linux QA операции достигна timeout; отделните повторения преминаха без увеличение на лимити (предходно измерване: 17.24 s / 602.01 MiB). Отказът и ограничението са записани в concurrent отчета.

Page timeout ~45 s, worker address-space boundary 1 GiB, raster budget 16M pixels, word/output/input limits и parser slots не са увеличавани. Unix worker е private process group; timeout/cancellation и worker crash убиват останалите OCR descendants. Съществуващото production Compose `init: true` осигурява reaping на orphan/zombie процеси; Linux negative QA използва същата граница и изисква PID да изчезне. Windows запазва Job Object границата. Worker TMPDIR/TEMP/TMP сочат private parent-owned директория: PNG/cell файловете се почистват и при принудително прекратяване, когато worker finalizers не могат да се изпълнят. Timeout/crash тестът проверява и липсата на тези файлове. OCR може да се изключи чрез съществуващата настройка; publication gate остава активен.

## 15. Регресии и проверка

Новите тестове покриват независим native fallback след invalid table; partial/empty bands; physical coverage; nonsequential positions; competing readings; duplicate areas; отделни еднакви occurrences; human correction + changed occurrence set; N selected lists; later-page context; foreign-document rejection; stale request; worker/child timeout и sanitized environment.

Linux runtime smoke съдържа 11 реални OCR случая: обикновена grid таблица, SMask, 90/180/270°, 1.5° skew, 0.75×/1.5× resolution, borderless, празно quantity и немски описания с umlaut. Включва wrapped description и exact values/provenance assertions. Smoke е добавен към Docker CI job.

Запазени са 03A publication/direct API/stale/concurrency regressions, existing native/scan/schema/geometry/multipage tests, PARTS-DOC, snapshots, official documents, HPWJ/611 source rows и authorization inventory. Точните финални команди, резултати и ограничения са в QA verification отчета.

| Локална проверка | Резултат |
|---|---|
| Linux extraction / durable review / multipage / process boundaries | 83 passed, 3 warnings, 238.87 s; последвани от 2/2 финални timeout/crash + PNG cleanup проверки (2.69 s) |
| Финални adaptive/durable/authorization инварианти | 55 passed, 3 warnings, 146.70 s; включително shifted occurrences, page word budget и parent PNG cleanup |
| PostgreSQL 16: N-source context + concurrent review/NOWAIT transaction release | 2 passed, 3 warnings, 100.31 s |
| Frontend full Vitest, BG/EN/RU parity | 589 passed / 64 files; пълен повторен прогон след един QR timeout при натоварване, без промяна на assertions |
| Финални GuidedParts/GuidedBuilder/RevisionVisualSources | 13 passed / 3 files; след word-budget предупреждението още 6/6 GuidedParts + typecheck/lint PASS |
| Typecheck, lint, frontend build, Ruff, compileall | PASS; съществуващ Vite chunk-size advisory |
| Migration history / authorization inventory | 33 protected migrations; 281 routes / 145 mutating, PASS |
| Release verifier / verified source anchors | 26/26, 19 машини / 611 части, PASS |
| Python/frontend dependency audits | PASS, 81/342 dependencies, 0 blocking findings |
| Linux image + реални CLI OCR / LibreOffice / PARTS-DOC smokes | PASS; 11 adaptive OCR случая + съществуващ OCR, runtime, appendix и Builder DOCX/PDF |
| D13 exact / Edge browser | 3×30/30 Linux, 3×30/30 Windows; UI correction/refresh/retry/source-review gate PASS, 0 page errors |

Пълните локални Windows backend/PostgreSQL серии са **прекъснати, не PASS**: около 87 min, backend progress 50% и PostgreSQL 64 progress marks без отчетен отказ, при 678 MiB свободна RAM от 8127 MiB. Backend серията е започнала преди последните допълнителни тестове. Спрени са само собствените QA process trees; PostgreSQL wrapper е почистил собствения си контейнер/volume. Начални PostgreSQL readiness и LibreOffice conversion откази при това натоварване са последвани от успешни изолирани повторения. Допълнителен прогон на 55 теста имаше един timeout при synthetic PDF upload в setup, преди authorization assertions, едновременно с Docker frontend compilation; пълният изолиран повторен прогон е 55/55 PASS. Лимитите и assertions не са отслабени.

Окончателният пълен backend/SQLite, PostgreSQL, frontend и Docker резултат се потвърждава чрез GitHub Actions върху точния PR HEAD; immutable CI URL, counts и ограничения се предават в PR описанието. Незавършените локални серии не се представят като заместител на този CI резултат. Машинночетими локални доказателства: [QA verification](qa/catalog-builder-03b/verification.json).

## 16. Ограничения

Borderless completeness се оценява предпазливо по текстови области; няма гаранция за откриване на всеки невидим/нечетим ред. Deskew е ограничен до малък наклон; сложни merged cells, силно повредени/извити сканове и таблици над cell/pixel/deadline budget могат да изискват ръчен mapping/transcription. Не се повишават ресурси, за да бъдат скрити такива случаи.

Windows CLI е локален QA инструмент, не нов distribution канал. Production acceptance е Linux Docker. Външни OEM manuals за всички производители не са добавяни; manufacturer-neutral регресиите допълват реалния D13, без да доказват универсална точност.

## 17. Сигурност и обратна съвместимост

Няма външни OCR/AI API, shell invocation или изпращане на OEM съдържание. CLI аргументите са фиксирани; user text не става команда. Parser environment не наследява DB/application/licence secrets. Процесните/resource граници, protected PDF preview/evidence endpoints и centralized permissions остават активни. Нови роли/маршрути няма.

Миграции 0001–0033 не са променяни. Няма VERIFIED backfill. Старите attempts/drafts се възобновяват чрез 03A ledger; published/retired revisions, signed DOCX/PDF, snapshots, machine IDs, Falch numbering, HPWJ seed, source registers и factory fingerprints не се променят. Publication digest включва актуалното review състояние и concurrent/stale промяна не може да го прескочи.

Работено е само в development и изолирани QA ресурси. Production директория, DB, конфигурации, услуги и публичната инсталация не са достъпвани. Няма deployment или merge.

Browser QA сървърите са спрени и собствените PostgreSQL контейнери/volumes са почистени. Автоматична проверка отказа изтриването на временните локални browser SQLite файлове с „blocked by policy“; те са запазени извън Git, заедно с локалните QA доказателства.

## 18. Остава за 03C

Цялостното опростяване на интерфейса, премахването на общия Advanced Mode, обединената финална UX таблица, контекстните cell crops и hotspot UX остават за отделно разрешен PR 03C. В 03B има само group processing, coverage предупреждения и retry в настоящия workflow.

**30/30 извлечени части не означава 30 проверени hotspots.** D13 callout 48 срещу списъчна позиция 38 остава отделно неразрешено несъответствие. Не се измисля marker и не се заменя позиция автоматично.

Технически източници: [Tesseract CLI/TSV и batch input](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html), [PyMuPDF page/image API](https://pymupdf.readthedocs.io/en/latest/page.html), [PyMuPDF image/mask composition](https://pymupdf.readthedocs.io/en/latest/recipes-images.html).
