# Архитектура на AssetCore

## Слоеве

- `backend/app/main.py` дефинира FastAPI маршрутите и ролевите зависимости.
- `backend/app/models.py` съдържа SQLAlchemy модела и стабилните enum кодове.
- `backend/app/schemas.py` е Pydantic договорът, включително legacy входна съвместимост.
- `backend/app/industrial_schemas.py` е договорът за паспорти, configurable categories, ремонти, каталог, библиотека, шаблони и administration.
- `backend/app/industrial_api.py` съдържа универсалните индустриални API модули и provenance/approval границите.
- `backend/app/workflow.py` централизира позволените машинни и ремонтни преходи и completion gates.
- `backend/app/transfer_service.py` е транзакционният домейн за издаване, връщане, партиди и документи.
- `backend/app/document_generation.py` генерира индивидуалните DOCX/PDF snapshots и безопасни имена.
- `backend/app/localization.py` локализира backend съобщения и статусни етикети без промяна на съхранените стойности.
- `backend/alembic` е единственият поддържан път за промяна на схемата.
- `frontend/src/api.ts` е удостовереният API клиент и изпраща `Accept-Language`.
- `frontend/src/i18n.tsx` съдържа централния BG/EN/RU речник, форматиране и status mapping.
- `frontend/src/App.tsx`, `BulkTransfers.tsx` и `IndustrialPlatform.tsx` реализират responsive PWA екраните, глобалното търсене и цифровия паспорт.

## Домейн и транзакции

Активното индивидуално предаване, не свободният текст на машинния статус, е авторитетът за наличност. Издаването и връщането валидират всички избрани машини в една транзакция. PostgreSQL използва row locking и partial unique index за едно активно предаване; SQLite използва съвместим unique индекс и serialized write поведение за разработка и тестове. Integrity конфликтите се преобразуват в HTTP 409 без частични записи.

Партидата е обща проследима референция, но всяка машина има собствено предаване, протокол и състояние. Частичното връщане не затваря останалите записи.

## Данни и история

`docs/SOURCE_REGISTER_BG.md` и провереният seed са източникът на истина за 19-те HPWJ машини. Seed-ът допълва или актуализира само проверения регистър и не изтрива бъдещи категории. Audit, repair, transfer и document записите не се пренаписват в нормален workflow.

`AssetCategory` и `CategoryFieldDefinition` описват динамичен паспорт без schema migration за всяко ново поле. `Location` и `Department` са деактивируеми справочници: старите записи не се изтриват и историческите връзки остават валидни. `MachineEvent` е общата asset timeline. `GeneratedDocument` пази bytes, hash, snapshot, език, template version, actor и връзка към машина/ремонт/заявка/предаване/партида. `TechnicalDocumentRevision` пази всяка библиотечна версия, `PartCatalogImage` и `PartRequestAttachment` пазят проверени файлове и SHA-256, а `PartHotspot` и `RepairKit` остават непроверени до изрично човешко потвърждение.

Оригиналните DOCX/PDF файлове са контролирани референции, не автоматично потвърдени структурирани данни. Импорт от OCR, комплектовки и нови asset категории изисква източник, confidence и човешко потвърждение.

## Разгръщане

Локалната среда и тестовете използват SQLite; Render и Docker production използват PostgreSQL. Приложението изпълнява Alembic upgrade преди seed. Secrets се подават само през средата и никога не влизат в API отговор, frontend bundle или Git.
