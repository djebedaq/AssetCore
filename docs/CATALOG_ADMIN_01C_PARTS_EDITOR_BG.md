# CATALOG-ADMIN-01C: чернови части и страници на списъци

## Модел

`CatalogRevisionAssembly → CatalogRevisionPart → CatalogRevisionPartPageMap → CatalogRevisionVisualPage(SPARE_PARTS_LIST)`.

Всеки чернови ред принадлежи на точно един възел. Идентичността е тройката `(assembly_id, position, part_number)`: една позиция може да има варианти с различни номера. Номерът на частта не е глобален ключ. Задължителни са позиция, номер и поне едно от BG/EN/RU име или описание. `quantity` е незадължителна неотрицателна числова стойност; `quantity_raw` пази текстовата стойност от източника без автоматично тълкуване.

Връзката към източник пази ID на изрично декларирана визуална страница. Сървърът допуска само `SPARE_PARTS_LIST` от PDF в същия възел. `visual_page_id` определя точния PDF, номер на страница и роля. Име на файл, поредност и номер на позиция никога не служат за идентичност. Изтриване на страница, PDF, част или възел премахва съответните чернови връзки в една транзакция и се одитира.

## Редактор и API

Администратор с `PARTS_MANAGE` може да чете, създава, редактира и изтрива части през `/api/admin/catalog-builder/assemblies/{assembly_id}/parts` и `/api/admin/catalog-builder/parts/{part_id}`. Страниците за избор са в `/assemblies/{assembly_id}/spare-list-pages`; връзките са в `/parts/{part_id}/source-pages` и `/part-page-maps/{mapping_id}`. Четенето на историческа чернова е разрешено. Всяка мутация изисква активен каталог и ревизия `DRAFT`. `READY` се изчислява при четене, когато валидна част има поне една допустима страница; иначе е `INCOMPLETE`.

## CSV: преглед и потвърждение

`POST /assemblies/{assembly_id}/parts/import-preview` приема UTF-8 CSV като base64, проверява до 512 KiB и 1000 реда и връща всеки ред с нормализирани полета, грешки, предупреждения и разрешени ID на страници. Прегледът не пише в базата. `POST /assemblies/{assembly_id}/parts/import-confirm` приема подписан, обвързан с администратор и възел токен с 15-минутен срок. Сървърът проверява отново редовете, съществуващите части и изричните роли на страниците, преди атомично създаване. Грешка блокира всички редове. Предупреждение за ред без страница изисква изрично потвърждение. Дубликат във файла или конфликт с вече съществуваща част е грешка, без презаписване.

Колони: `position`, `part_number` (задължителни); `name_bg`, `name_en`, `name_ru`, `description`, `quantity`, `quantity_raw`, `unit`, `manufacturer`, `category`, `replaced_by_part_number`, `alternative_part_number`, `technical_specification`, `technical_notes`, `supplier`, `supplier_code`, `source_page`, `source_artifact_sha256`. Ако `source_page` съвпада с повече от един PDF, редът е грешен до указване на точния SHA-256. Не се прави PDF текстово извличане или OCR.

## Изолация

01C попълва само Builder staging таблиците `catalog_revision_parts` и `catalog_revision_part_page_maps`. Няма публикация към `PartCatalog`, `CatalogVisualPartMap`, заявки за части, ремонтни комплекти или официални документи. Бъдещата 01E ще валидира и преобразува данните атомично към live каталога. 01D ще обработва разглобени схеми и геометрия.
