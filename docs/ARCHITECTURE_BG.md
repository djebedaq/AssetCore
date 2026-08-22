# Архитектура на AssetCore

## Слоеве

- `backend/app/main.py` дефинира FastAPI маршрутите и ролевите зависимости.
- `backend/app/models.py` съдържа SQLAlchemy модела и стабилните enum кодове.
- `backend/app/schemas.py` е Pydantic договорът, включително legacy входна съвместимост.
- `backend/app/industrial_schemas.py` е договорът за паспорти, configurable categories, ремонти, каталог, библиотека, шаблони и administration.
- `backend/app/industrial_api.py` съдържа универсалните индустриални API модули и provenance/approval границите.
- `backend/app/workflow.py` централизира позволените машинни и ремонтни преходи и completion gates.
- `backend/app/repairs/service.py` прилага ремонтните преходи и задължителното document persistence без commit; API маршрутът остава собственик на транзакцията.
- `backend/app/transfer_service.py` е транзакционният домейн за издаване, връщане, партиди и документи.
- `backend/app/document_generation.py` генерира индивидуалните DOCX/PDF snapshots и безопасни имена.
- `backend/app/application_errors.py` дефинира общия безопасен production error договор, diagnostic ID и структуриран log context.
- `backend/app/catalog/` е отделният authoritative каталог domain: `routes.py` пази HTTP/permission договора, `service.py` прилага family/source integrity правилата, `repository.py` ограничава активните заявки, `importer.py` извършва идемпотентно архивиране/upsert, а `validation.py` проверява immutable source manifest и dataset.
- `backend/resources/catalog/v2/manifest.json` и разделените JSON файлове са versioned immutable projection на точно деветте файла под `backend/resources/technical_docs/PARTS_CATALOG/`; `backend/scripts/build_catalog_v2.py` е възпроизводимият extractor, а `catalog_v2_validation.py` е release gate.
- `backend/resources/catalog/enrichment/v1/` е отделен non-authoritative EN/BG display слой. Генерираният record map е keyed единствено по canonical `source_record_key`; `translations.py` валидира пълно 611-record coverage и source fingerprint binding, без да записва translation текст в source projection или PDF fingerprint.
- `backend/app/localization.py` локализира backend съобщения и статусни етикети без промяна на съхранените стойности.
- `backend/alembic` е единственият поддържан път за промяна на схемата.
- `frontend/src/api.ts` е удостовереният API клиент и изпраща `Accept-Language`.
- `frontend/src/i18n.tsx` съдържа централния BG/EN/RU речник, форматиране и status mapping.
- `frontend/src/App.tsx`, `BulkTransfers.tsx` и `IndustrialPlatform.tsx` реализират responsive PWA екраните, глобалното търсене, каталога и цифровия паспорт; `industrialUi.tsx` съдържа повторно използваните modal/document/attachment presentation действия.
- `frontend/src/features/repairs/IndustrialRepairs.tsx` е самостоятелният repair screen, `repairApi.ts` е типизираната му API граница, а `workflow.ts` пази stage/form/payload договора без React state.
- `frontend/src/features/catalog/` е самостоятелният machine-first каталог screen. `catalogApi.ts` пази focused API calls, `catalogState.ts` — deterministic cart/kit merge правилата, `catalogInteraction.ts` — pointer/touch state machine-а и movement threshold-а, а `IndustrialCatalog.tsx` — responsive diagram/table/cart workflow без hardcoded production URL или технически source данни. `CatalogSelectionPanels.tsx` притежава достъпния focus-trapped desktop modal/mobile sheet договор.
- `frontend/src/features/catalog/catalogNames.ts` е единствената presentation функция за `English / Български` и отделния manufacturer source текст; table, hotspots, variants, repair kits, modal/sheet и request cart не дублират translation логика.

## Authoritative каталог за резервни части

Активният dataset е само `PARTS_CATALOG_V2`: 611 source реда от FALCH_500, FALCH_1000 и HYDWIN_FUSSEN_500. Семейството се определя чрез exact brand/model плюс проверен inventory number от manifest-а; няма fuzzy matching. CombiJet, машина №19 и всеки неподдържан модел получават празен каталог, не чужди части.

`PartCatalog.source_record_key` е уникалната identity на source реда. Тя пази repeated positions/applicability variants, които старият ключ `brand + model + assembly + position + part_number` не можеше да представи без overwrite. Оригиналният номер, `Replaced by`, `quantity_raw`, `Valid for`, repair-kit code, source page/version/hash и anomaly codes остават отделни полета.

`CatalogDiagram` свързва exact PDF page с контролиран `TechnicalDocument`. `CatalogPositionHotspot` е position-centric, а не `hotspot → part`: една позиция може безопасно да върне няколко source variants, а повторен указател има собствена област. Всички 581 действително отпечатани BOM позиции върху 12-те diagram страници са представени с 818 production-approved области: 774 `AUTO_MATCHED` и 44 exact `MANUALLY_CONFIRMED`. И двата provenance типа са активни и еднакво използваеми от механик; provenance се вижда само в QA режима. Два BOM реда `0` за цели възли проверено не са отпечатани. Административна корекция изисква `parts.manage`, причина и audit запис, става `MANUALLY_CONFIRMED` и има precedence при следващ import.

`RepairKit`/`RepairKitComponent` се използват повторно, но active/approved records се rebuild-ват само от изричната Falch колона `Repair kit`. Source quantity за kit component не се смесва с order quantity при единичен избор. Старите каталог, kit и technical-document DB записи се деактивират, вместо да се изтриват, за да останат четими историческите ремонти и заявки.

Всеки read път проверява текущия SHA-256 на source файла. Липсващ или променен source връща безопасен `ApplicationError` с `catalog_source_integrity_failed`, `operation=catalog_read` и `stage=source_integrity`; непроверен dataset никога не се показва като verified.

## Домейн и транзакции

Активното индивидуално предаване и незавършената ремонтна карта, не свободният текст на машинния статус, са авторитетът за наличност. Оперативният `MachineStatus` съдържа само `READY`, `ISSUED` и `REPAIR`; подробните етапи се пазят в `RepairStatus`. Издаването и връщането валидират всички избрани машини в една транзакция. PostgreSQL използва row locking и partial unique index за едно активно предаване; SQLite използва съвместим unique индекс и serialized write поведение за разработка и тестове. Integrity конфликтите се преобразуват в HTTP 409 без частични записи.

Партидата е обща проследима референция, но всяка машина има собствено предаване, протокол и състояние. Частичното връщане не затваря останалите записи.

Приемането разрешава активното местоположение `Цех` по име вътре в транзакцията. Избор `REPAIR` създава един `Repair`, свързан чрез `source_return_transfer_id`, `source_return_document_id` и `source_return_batch_id`. Stage requirements са централизирани в `workflow.py` и се оценяват server-side след заключване на ремонта. Активните преходи са само `ACCEPTED → DIAGNOSIS → REPAIRING → COMPLETED`; legacy `WAITING_APPROVAL`, `WAITING_PARTS` и `TESTING` остават само в enum/i18n/history compatibility и се нормализират от Alembic. UI progress индикаторът не извършва произволни mutations.

Participant mutation използва нормализиран `identity_key` и уникален `(repair_id, identity_key)` индекс, затова UI double click и конкурентни заявки не могат да създадат два записа. Новите редове изискват положително `minutes_worked`; историческите participant snapshots могат да останат с `NULL` key/време и не се пренаписват от миграцията.

Repair completion, записът на реалния approver, генерирането на задължителния тричастов вътрешен DOCX/PDF, `Repair.status=COMPLETED`, `Machine.status=READY` и location resolution на активния `Цех` са една транзакция. Неуспешен генератор или persistence конфликт връща операцията до предишния ремонтен етап и пази машината `REPAIR`.

`main.py` и `industrial_api.py` са route owners: проверяват permission/request договора, извикват публичния repair service и commit-ват само след успешно записани документи, events и audit. `apply_repair_transition()` и document generator-ът никога не commit-ват. Името `generate_completion_documents_or_rollback()` прави изричен факта, че document failure връща цялата текуща owner транзакция. Така legacy и текущият маршрут използват една и съща бизнес логика.

Document слоят получава canonical SQLAlchemy snapshot и връща `GeneratedDocument` записи/bytes/hash metadata. Той не решава permission, machine status или repair transition. Signature подготовката и финализацията остават в `transfer_signing.py` и `signature_rendering.py`; `transfer_service.py` управлява транзакционното им включване, без промяна на manifest, reuse protection или PostgreSQL locking.

## Грешки и structured logging

Очакваните validation/business откази пазят текущите HTTP 409/422 кодове и конкретни български съобщения. Неочаквана критична workflow грешка се преобразува до безопасен договор с `code`, `message`, `operation`, `stage` и `diagnostic_id`. Server log-ът съдържа traceback и само изрично подаден контекст като `machine_id`, `repair_id`, `transfer_id`, `batch_id`, `document_id` и `user_id`. Пароли, token-и, signature bytes, encryption keys и request bodies не се подават като context.

### Как се диагностицира production bug

1. Копирайте `diagnostic_id` от UI/API отговора; не копирайте credentials или подписи.
2. Намерете същия ID в Render/server logs и проверете `operation` и `stage`.
3. Използвайте само записаните entity ID стойности, за да намерите свързаните machine/repair/transfer/batch/document и audit записи.
4. Възпроизведете проблема върху изолирана SQLite или PostgreSQL test база със същия API договор, без production snapshot промени.
5. Добавете regression тест, който доказва както отказа, така и пълния rollback.
6. Приложете минималната корекция и изпълнете domain тестовете, пълния pytest, frontend QA и PostgreSQL smoke.
7. Съпоставете diagnostic ID със commit/PR и запазете audit/document history непроменени.

## Данни и история

`docs/SOURCE_REGISTER_BG.md` и провереният seed са източникът на истина за 19-те HPWJ машини. Seed-ът допълва или актуализира само проверения регистър и не изтрива бъдещи категории. Audit, repair, transfer и document записите не се пренаписват в нормален workflow.

`AssetCategory` и `CategoryFieldDefinition` описват динамичен паспорт без schema migration за всяко ново поле. `Location` и `Department` са деактивируеми справочници: старите записи не се изтриват и историческите връзки остават валидни. `MachineEvent` е общата asset timeline. `GeneratedDocument` пази bytes, hash, snapshot, език, template version, actor и връзка към машина/ремонт/заявка/предаване/партида. `TechnicalDocumentRevision` пази всяка библиотечна версия, `PartCatalogImage` и `PartRequestAttachment` пазят проверени файлове и SHA-256, а `PartHotspot` и `RepairKit` остават непроверени до изрично човешко потвърждение.

Оригиналните DOCX/PDF файлове са контролирани референции, не автоматично потвърдени структурирани данни. Импорт от OCR, комплектовки и нови asset категории изисква източник, confidence и човешко потвърждение.

## Разгръщане

Локалната среда и тестовете използват SQLite; Render и Docker production използват PostgreSQL. Приложението изпълнява Alembic upgrade преди seed. Secrets се подават само през средата и никога не влизат в API отговор, frontend bundle или Git.
