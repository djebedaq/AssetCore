# CATALOG-GUIDED-BUILDER-01 — референции, страници и резервни части

## Работен поток

Каталог → човешки създадени референции → логически страници → оригинални PDF източници → избрани схеми и списъци → извличане само на списъците → преглед и потвърждение → ръчно поставяне на позиции → проверка → публикация.

Референцията е съществуващият Builder възел (`CatalogRevisionAssembly`). Потребителят задава името; няма автоматично откриване, превод или създаване на групи. Логическата страница (`CatalogRevisionReferencePage`) е самостоятелна единица с UUID, стабилен DB идентификатор, ред, незадължително заглавие, версия и автор/време. Номерът „Страница 1“ е презентационен ред, а не физически PDF номер. Пренареждането не променя идентичността.

Една логическа страница може да има няколко схеми и няколко списъка, включително от различни PDF. Една физическа страница може изрично да има и двете роли или да се използва в други логически страници. Изборът използва до осем lazy thumbnails, произволен physical-page jump и проверени source assignments. Частта е уникална по логическа страница + позиция + номер. Повторена позиция на друга страница е независима; вариантите се ограничават до текущата страница.

## Съхранение и миграция

Неприложената PR миграция `20261001_0031` добавя `catalog_source_blobs`, `catalog_revision_reference_pages`, nullable logical-page FK и ред към visual assignments, nullable logical-page FK и extraction identity/evidence към части. Частичните unique индекси запазват стария legacy scope, когато FK е NULL, и отделят новия guided scope. Старите приложени миграции 0025–0030 не се променят.

Оригиналът се съхранява веднъж по точен SHA-256. Artifact aliases съдържат метаданни и FK към blob, без копие на байтовете. Новите технически документи и версиите им използват същия blob. Исторически inline файлове остават четими; няма мигриране или преизчисляване на PARTS-DOC история. Downgrade отказва загуба на използвани нови структури.

Whole-document run/page/candidate таблиците, автоматичното group/page-role matching, callout matching и review orchestration са премахнати. Няма втори скрит pipeline или job scheduler.

## Upload и граници

Основният endpoint е `POST /api/admin/catalog-builder/revisions/{id}/pdf` с multipart `file`, FastAPI UploadFile и ограничено четене на порции. Browser изпраща File директно чрез XHR; показва upload progress и validation status. Няма Base64 за нормалния upload. Legacy JSON/manual инструменти остават за съвместимост.

| Настройка | Default |
| --- | --- |
| CATALOG_PDF_MAX_BYTES | 268435456 (256 MiB) |
| CATALOG_PDF_MAX_PAGES | 5000 |
| CATALOG_EXTRACTION_PAGE_TIMEOUT_SECONDS | 45 |
| CATALOG_EXTRACTION_MAX_PROCESSES | 2 на application worker |
| CATALOG_EXTRACTION_MAX_WORDS | 30000 на страница |
| CATALOG_OCR_ENABLED | true |
| CATALOG_OCR_LANGUAGES | eng+deu+bul+rus |
| CATALOG_OCR_DPI | 150 |
| CATALOG_OCR_MAX_PIXELS | 16000000 |

Подписът и структурата на PDF се проверяват в изолиран subprocess. MIME и filename са само метаданни. Password-protected/repaired/malformed документи се отхвърлят с технически код без host paths. Размерът и страниците дават 413 с действителен limit и име на конфигурируемата настройка. Успешната validation metadata се кешира до 32 точни SHA/config ключа, без bytes; текущите bytes винаги се хешират.

Операцията има timeout, ограничени едновременни процеси, word/pixel/page/dimension граници и Linux resource limits / Windows Job Object. Subprocess изпълнява фиксиран Python worker с argument array, без shell, DB credentials, external URLs или cloud upload. Private temporary directories се изчистват и при грешка. Metadata validation не анализира таблици на неизбрани страници.

## Извличане и ръчно уточняване

`parts_extraction/` разделя process boundary, selected-page layout, local OCR, geometry, schema inference и row normalization. Първо PyMuPDF native text/word координати и ruled tables; след това coordinate-aware borderless region/column анализ. Няма производител-специфична структура. Лексикалните EN/DE/BG/RU заглавия са доказателство за колоните, а не гаранция. Числовите/alphanumeric позиции и номера, quantity, description, notes/specification се запазват отделно от source cells и raw text.

Wrapped descriptions се обединяват само при доказана структура. Repeated headers се изключват от part rows. Adjacent selected physical pages могат да използват предишната column geometry само от същия SHA; такава continuation винаги е маркирана за преглед. Не се създават части от липсващи номера или двусмислени колони. Preview съдържа exact SHA, artifact, visual assignment, физическа страница, row bbox/raw text/cells, method, warnings и `SPARE_PARTS_1` версия.

Нееднозначна таблица показва оригиналните headers и cell samples. Потребителят избира Position, Part number, Description, Quantity, Notes, Specification или Skip за всяка колона. Mapping е уникален и изисква position/part_number/description. Повторното четене използва подписаните raw cells без повторен PDF parse/OCR. Нормализираните стойности се редактират в малък преглед. Филтрите показват всички, предупреждения, редове без предупреждения, липсващи данни, потвърдени или отхвърлени. Отхвърлянето/възстановяването е локално до потвърждението; оригиналът е достъпен до прегледа. CSV и пълният ръчен editor са в разширените инструменти.

## OCR

OCR се използва само за избран списък без достатъчно native text. Docker включва Tesseract с eng/deu/bul/rus. Windows използва локална налична Tesseract/PyMuPDF среда; липсата на runtime/languages се feature-detect-ва и дава OCR_UNAVAILABLE, без fabricated text. Смесен PDF не се OCR-ва изцяло. OCR-derived rows изискват човешки преглед. Няма cloud AI/API dependency. OCR coordinates са доказателство за реда; не се използват за автоматични hotspots.

## Преглед, атомичност и audit

Preview е HMAC-подписан, actor/logical-page/version/source-bound, с 15-минутна валидност и ограничен payload. Клиентът не може да подмени source evidence. Preview/mapping не създават trusted DB части. Confirm записва избраните човешки стойности и автоматично exact `CatalogRevisionPartPageMap` в една транзакция. При невалиден ред/duplicate конфликт целият confirm се връща назад.

Stable extraction key е SHA + physical page + row bbox + raw source text в logical-page scope. Повторното потвърждение пропуска съществуващата част и не презаписва човешките корекции. Повторен upload връща съществуващия source. Page/source edits използват optimistic version и established catalog/revision locks; stale assignments/reorder се отхвърлят. References/pages/sources reorder е атомичен. Изтриване на използван source/page се блокира. Изтриване през legacy artifact endpoint не може да изтрие guided assignments. Само DRAFT се редактира; Owner/Admin checks са централизирани в PARTS_MANAGE.

Audit обхваща upload, human reference/page CRUD и reorder, source assignment/removal, preview/OCR method, manual column mapping, part confirmation, manual hotspot creation/edit/delete/verification, publication и binding. Не се записва event за всеки extraction token. Непотвърден preview се губи при затваряне/reload; UI предупреждава за unsaved работа. При token expiry повторете selected-page extraction.

## Ръчни позиции и runtime

На избраната логическа страница Builder показва само нейните позиции и схеми. Marker click върху самото изображение веднага показва overlay, записва, проверява при включена human auto-verify опция и преминава към следващата незавършена позиция. Rectangle drag, select/move/resize, pan, zoom, touch, pointercancel остават. Има предишна/следваща/skip, друга occurrence и undo на последното успешно поставяне. Без части има изрично обяснение. Проверка никога не възниква от extraction algorithm.

Coverage е union на всички схеми в текущата логическа страница. Допустими са няколко места за една позиция. Вариантите на частите се показват само в тази страница. В runtime parent reference има подредени логически page tabs и отделни Scheme 1/2 tabs. Runtime source identity включва logical-page ID; legacy HPWJ sources и APIs работят без page FK. Един публикуван каталог може да се свърже с няколко съвместими машини.

Readiness изисква схеми, списъци и части за всяка guided страница, валидни source maps и проверена hotspot coverage за всички нейни позиции. Няма publish при cross-page map/hotspot или непроверена зона. Legacy readiness policy се запазва. Publish създава immutable runtime graph; clone remap-ва reference pages, parts, maps, hotspots и kit relations с нови DB IDs, същите page UUID и общ original blob. Existing PARTS-DOC snapshots запазват exact source provenance.

## Offline QA и граници на точността

```powershell
.venv/Scripts/python.exe scripts/catalog_spare_parts_smoke.py "manual.pdf" --page 13 --no-ocr
.venv/Scripts/python.exe scripts/catalog_spare_parts_smoke.py "manual.pdf" --pages 13,15
```

CLI е DB-free/read-only, приема само избрани physical pages и връща JSON evidence. Не предлага assemblies, page roles или hotspots. QA PDFs са локални и не се commit-ват. Tests генерират synthetic fixtures за native/mixed/OCR, кирилица, rotated/landscape, borderless/ruled/multipage tables, shared sources, stale actions, scoped repeated positions, publication/runtime/PARTS-DOC и PostgreSQL конкуренция.

Не се обещава 100% accuracy. Damaged scans, нестандартни шрифтове и geometry, footnotes/variants или неясни column meanings могат да изискват ръчно mapping/edit/add. Източникът и човешкото потвърждение са авторитетни. Няма автоматично превеждане на описания; source description се показва чрез съществуващия locale fallback, без да се записва като фиктивна преведена стойност.
