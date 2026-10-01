# Автоматично разчитане на PDF каталози — CATALOG-AUTO-INGEST-01

## Работен процес

В опростения Catalog Builder: каталог → оригинален PDF → автоматичен анализ →
преглед на групи и страници → преглед на извлечени части → преглед на маркировки →
проверка за готовност → публикуване. CSV е резервен инструмент в разширените
инструменти. Не е необходим CSV за нормалното разчитане.

Първо се приемат групите, след това страниците и частите. При приемане на част
автоматично се създава връзката към физическата BOM страница. Предложенията за
маркировки се приемат непроверени; отделното потвърждение означава човешки преглед.
При няколко места се показват всички координати. Липсваща позиция се маркира
ръчно или предложението се отхвърля след проверка. Съществуващите редактори за
части, групи, страници, маркировки и ремонтни комплекти остават достъпни.

## Архитектура и съхранение

Миграция `20261001_0031` добавя `catalog_source_blobs`, `catalog_ingest_runs`,
`catalog_ingest_pages` и `catalog_ingest_candidates`. Новите Builder артефакти,
алиаси за групи, клонирани версии и публикувани технически документи сочат към
един SHA-256 blob. Оригиналните байтове не се препакетират. Съществуващите byte
колони и исторически записи не се променят. ORM достъпът към `content` и
`uploaded_content` разрешава както старото съдържание, така и новата връзка.
PARTS-DOC продължава да записва собствените си неизменяеми доказателства.

Разчитането е разделено между `source_storage.py` и модулите в
`backend/app/catalog_admin/ingest/`: process/worker, extraction, tables,
candidates, runs, review, schemas и routes. Публикуването продължава през
съществуващия атомарен Builder → runtime механизъм. Един каталог може да се
свърже с множество съвместими машини.

## Качване и конфигурация

Основният endpoint е `POST /api/admin/catalog-builder/revisions/{id}/pdf`,
`multipart/form-data`, с поле `file` и незадължително `title`. Браузърът подава
оригиналния `File` чрез XHR и показва upload progress; няма FileReader или Base64.
UploadFile използва spool, а сървърът чете ограничени 1 MiB блокове и изчислява
SHA-256. Същият SHA в същата версия връща съществуващия документ. Името е само
метаданни. Реалният PDF header и структура се проверяват независимо от MIME.
Защитените с парола, повредените и прекалено големите файлове имат отделни грешки.
Старият Base64 JSON endpoint се запазва за съвместимост и има собствен schema cap.

| Променлива | По подразбиране | Значение |
|---|---:|---|
| `CATALOG_PDF_MAX_BYTES` | 268435456 | 256 MiB за оригиналния PDF |
| `CATALOG_PDF_MAX_PAGES` | 5000 | Максимален брой физически страници |
| `CATALOG_INGEST_PAGE_TIMEOUT_SECONDS` | 45 | Timeout на отделния процес |
| `CATALOG_INGEST_MAX_PROCESSES` | 2 | Максимум едновременни parser процеси на application worker |
| `CATALOG_INGEST_MAX_WORDS` | 30000 | Максимум думи на страница |
| `CATALOG_OCR_ENABLED` | true | Локален OCR fallback |
| `CATALOG_OCR_LANGUAGES` | eng+deu+bul+rus | Tesseract езикови пакети |
| `CATALOG_OCR_DPI` | 150 | OCR резолюция |
| `CATALOG_OCR_MAX_PIXELS` | 16000000 | Ограничение преди OCR rasterization |

Операторът трябва да съгласува reverse proxy upload limits и временния дисков
капацитет с тези стойности. ASGI guard ограничава цялото multipart тяло до PDF
лимита плюс 1 MiB за envelope. Грешката за размер/страници показва стойността и
името на конфигурационната променлива. Няма migration/deployment към работеща
инсталация като част от разработката.

## Разчитане и доказателства

Първо PyMuPDF извлича native текст, думи, bounding boxes, размери, rotation и
font-based заглавия. Следват таблици с native cell borders и coordinate layout
fallback за таблици без рамки, OCR таблици и няколко колони. Синоними за позиция,
номер, описание и количество се разпознават без значение на регистъра на EN/DE/
BG/RU. Повторените headers не стават части. Description-only близко продължение
може да се добави към доказано предходния ред. Количествата са валидни decimals;
липсващо/неразчетено количество остава празно с предупреждение.

Страниците получават предложения `EXPLODED_SCHEME`, `SPARE_PARTS_LIST`, `BOTH`,
`OTHER` или `AMBIGUOUS`. Сигналите включват таблици, разположение на labels,
векторни рисунки и заглавия. Групите следват оригинални заглавия и съседство.
Изведените връзки са предложения, а не доверени факти. Не се генерират преводи:
оригиналното описание остава `description`; липсващите multilingual names
остават празни и runtime използва съществуващото fallback поведение. За група
оригиналното заглавие се използва като общо fallback име, без EN/RU копия.

OCR се използва само при недостатъчен native текст. Docker включва Tesseract и
eng/deu/bul/rus; на Windows тези пакети трябва да са инсталирани локално и
откриваеми от PyMuPDF. Липсващ runtime/пакет, изключен OCR или надхвърлен pixel
лимит се показват като предупреждения. Няма cloud API. PyMuPDF не предоставя
per-word Tesseract confidence чрез този API; OCR произходът се пази отделно и
всички OCR редове изискват преглед. Confidence стойностите са консервативни
евристики, не калибрирани вероятности.

Всяка анализирана страница пази ограничен raw text, координатни думи, headers,
table regions, labels, rotation, метод и предупреждения. Всеки part candidate
пази raw cells/row, page, bbox и source SHA. Прегледът показва оригиналната
страница до реда, с координатна област. Източникът винаги е авторитетен.

## Маркировки

BOM позициите са речник за същата предложена група. Native/OCR labels извън
таблици се сравняват точно с него. Размери с единици и headers/footers се
изключват. Bounding boxes се трансформират с rotation matrix към preview
координатите, добавят се 2 PDF points padding и се нормализират в [0,1].
`EXACT`, `MULTIPLE_CANDIDATES`, `NOT_FOUND` и `LOW_CONFIDENCE` различават случаите.
API допуска няколко избрани occurrence locations за една позиция. Ръчният
редактор позволява още маркировки, преместване и преоразмеряване.

„Преизчисли“ използва запазените координати след корекции на page/group/part
предложения. Вече прегледаните места не се заменят. Point mode показва draft
веднага при pointer down върху схемата; pointer up записва. Rectangle mode
показва геометрията при drag. Overlay selection и pan имат отделни gestures.
Липса на приети позиции се обяснява видимо; не се игнорират тихо кликове.

## Lifecycle, повторение и конкурентност

Ключът на run е revision + PDF SHA + `CATALOG_INGEST_1`. Candidate identities
включват вид, страница, bbox/row fingerprint или group/position. State е
`PROPOSED`, `NEEDS_REVIEW`, `ACCEPTED`, `REJECTED`. Source evidence не може да се
редактира през API. Human edits са отделен payload с actor/time и optimistic
version. Повторно разчитане запазва приети данни, редакции и откази.
Artifact ID в run е исторически snapshot; преди приемане се проверяват също
revision и SHA, защото SQLite може да използва повторно ID на изтрит draft alias.

Run checkpoint е след всяка страница. Кратките `advance` заявки се изпълняват
автоматично; DB lease предотвратява две едновременни PDF обработки за една
страница. Lease изтича след worker timeout плюс 30 секунди. Загуба на browser
или process позволява safe resume. Няма Redis/Celery. Retry повтаря неуспялата
страница; deliberate rerun използва кешираните страници и запазва решенията.
Прегледът и приемането са транзакционни и заключват catalog/revision както
съществуващите Builder writes. Bulk action е максимум 100 версиирани кандидата.
Извличането не държи DB row lock по време на native parsing/OCR.

## Сигурност, аудит и публикация

PDF parser/OCR е отделен процес с fixed arguments, stdin/stdout/stderr изключени,
wall timeout и 1 GiB memory bound: Linux RLIMIT_AS/CPU, Windows Job Object.
Временните файлове са generated names и се изчистват и при failure. Native
diagnostics не се връщат на клиент. Няма външни URL fetches или shell OCR команди.
Permission е централното `parts.manage`; всички writes са само за активен DRAFT.
Audit записва upload, start/completion/failure/retry/rerun/rematch и човешки
candidate actions/bulk review, без вътрешни token events.

RUNNING/FAILED анализ и всяко непрегледано предложение блокират publish.
При FAILED анализ човекът може изрично да отхвърли останалите предложения
(`DISMISSED`) и да довърши каталога с ръчните инструменти. Приетите факти и
evidence/cache остават; всички обичайни publication проверки продължават да важат.
Отхвърлени предложения не блокират финален пълен каталог. Съществуващите rules
за валидни части, source mapping и проверени hotspots се запазват. Липсващото
hotspot coverage остава предупреждение по досегашната продуктова политика.
Digest включва ingestion state/version, за да засече stale publication review.
Няма автоматично публикуване и няма mutation на публикувани версии/история.

## Ограничения и проверки

Необичайни OEM таблици, наклонени/повредени сканове, glyph outlines, неясни
заглавия, неразделими footnotes и нестандартни количества могат да изискват
ръчна корекция. Оригиналният документ е задължителен за проверка. Няма обещание
за 100% точност върху произволен PDF. Няма automatic repair-kit interpretation.
Приетите факти се коригират в съществуващите draft editors; re-analysis не ги
презаписва. За дълги документи оставете browser отворен за advance, или го
отворете отново за продължаване от checkpoint.

Тестовите PDF са генерирани в `tests/catalog_ingest_fixtures.py`, включително
native, Cyrillic, rotated/landscape, multipage/wrapped, ambiguity, protected,
scanned/mixed и файл над 12 MiB. Happy path използва действителния parser,
преглед и immutable publication. PostgreSQL тестовете използват disposable
QA schemas. Няма включени OEM manuals или промени във verified seed/register.
