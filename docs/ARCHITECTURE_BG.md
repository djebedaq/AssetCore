# Архитектура на AssetCore

## Слоеве

- `backend/app/main.py` сглобява FastAPI приложението и запазва legacy оперативните маршрути; asset HTTP маршрутите се включват от `assets/routes.py`, а `/locations` — от `master_data/routes.py`.
- `backend/app/models.py` съдържа SQLAlchemy модела и стабилните enum кодове.
- `backend/app/schemas.py` е Pydantic договорът, включително legacy входна съвместимост.
- `backend/app/industrial_schemas.py` е договорът за паспорти, configurable categories, ремонти, каталог, библиотека, шаблони и administration.
- `backend/app/industrial_api.py` сглобява индустриалния router и запазва provenance/approval границите извън asset/master-data домейните.
- `backend/app/assets/` притежава машинното четене/CRUD/QR (`service.py`), read-only паспорта (`passport.py`), типизираните полета (`custom_fields.py`) и машинните файлове (`attachments.py`). `routes.py` запазва HTTP/permission договора; `queries.py` и `serializers.py` съдържат съществуващия active-transfer read query и ограниченото machine представяне.
- `backend/app/master_data/` отделя категориите/дефинициите на полета и справочниците за местоположения/отдели. Транзакционните граници и audit действията са непроменени. Общите чисти attachment проверки са в `attachment_io.py`, а съществуващото commit-time IntegrityError преобразуване — в `persistence.py`. Вж. [картата на маршрутите и тестовото покритие за PR #32](ASSET_MODULARIZATION_BG.md).
- `backend/app/workflow.py` централизира позволените машинни и ремонтни преходи и completion gates.
- `backend/app/repairs/service.py` прилага ремонтните преходи и задължителното document persistence без commit; API маршрутът остава собственик на транзакцията.
- `backend/app/part_requests/service.py` централизира заключените submit/decision преходи, action-required query-то и document-eligible статусите без собствен commit.
- `backend/app/official_documents/registry.py` агрегира read-only каноничните и съвместимите historical transfer, repair и parts protocols. Той не генерира версии, не променя подписи/hash-ове и не записва audit; current official version има предимство пред legacy download редовете със същата domain identity.
- `backend/app/official_documents/integrity.py` централизира проверката и задаването на `current_version_id`, owner invariant-а и read-only диагностиката. Каноничният pointer е `NULL` само за historical/temporary съвместимост или сочи версия със същия `document_id`; PostgreSQL прилага composite FK и version trigger, а SQLite migration прилага еквивалентни triggers.
- `backend/app/transfer_service.py` е транзакционният домейн за издаване, връщане, партиди и документи.
- `backend/app/documents/` разделя генерирането на transfer, repair, parts-request и daily-report документи; `common.py`, `rendering.py`, `templates.py` и `registration.py` запазват съществуващите общи договори. `document_generation.py` е само explicit compatibility import слой. Template engine, signing и read-only official registry остават самостоятелни и непроменени. Вж. [модулната карта и output регресиите](DOCUMENT_MODULARIZATION_BG.md).
- `backend/app/application_errors.py` дефинира общия безопасен production error договор, diagnostic ID и структуриран log context.
- `backend/app/authorization_inventory.py` обхожда реалния FastAPI dependency graph и fail-ва затворено за mutating/public маршрут без точно permission/auth/allowlist основание; `backend/scripts/validate_authorization_inventory.py` е CI gate-ът.
- `backend/app/governance/` притежава owner, emergency и license HTTP/service домейните; `hardening_api.py` ги регистрира в същия ред и пази compatibility imports. Auth/owner prerequisites, locks, audit и transaction границите са непроменени. `licensing.py`, session/CSRF и security middleware остават централизирани. Вж. [картата на маршрутите, regression договорите и известния baseline read-only HTTP дефект](GOVERNANCE_MODULARIZATION_BG.md).
- `backend/app/auth_sessions.py` управлява hashed durable browser sessions,
  cookie policy, CSRF и revoke/cleanup lifecycle; `backend/app/auth_throttle.py`
  пази bounded HMAC-псевдонимизирани account/source backoff записи. React
  bootstrap-ва identity чрез `/api/auth/me` и не пази authorization truth или
  bearer credential в browser storage.
- `backend/app/web_security.py` централизира explicit CORS origins, browser security headers, CSP, HSTS само за production HTTPS и cache policy за API спрямо PWA assets.
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
- `frontend/src/features/partRequests/PartRequestsTracking.tsx` е history/action екранът „Заявени части“, а `PendingPartsBadge.tsx` визуализира permission-aware canonical count без unread/seen състояние.
- `frontend/src/features/officialDocuments/OfficialDocumentSection.tsx` визуализира общата responsive структура на трите read-only registry секции; `OfficialDocuments.tsx` зарежда единствено агрегирания registry договор и не смесва прегледа със signing mutations.

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

Всички writer пътища за официални документи използват integrity service-а след записване на версията. Repair correction освобождава временния pointer, премества съществуващата версия и едва тогава я задава като current на canonical документа; snapshot, binary content, hash-ове и signatures не се регенерират от integrity слоя.

Parts-request state machine-ът е `DRAFT → WAITING_APPROVAL → APPROVED → ORDERED → PARTIALLY_DELIVERED → DELIVERED`, с контролирани `REJECTED`, `CANCELLED` и return-to-draft разклонения. Catalog cart използва същия submit domain transition преди един общ commit. Подробният permission/audit/document договор е в [PART_REQUEST_WORKFLOW_BG.md](PART_REQUEST_WORKFLOW_BG.md).

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
