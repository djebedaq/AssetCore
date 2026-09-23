# PARTS-DOC-01A — неизменими визуални източници

Рендерирането на новите официални DOCX/PDF документи е описано в
`PARTS_DOC_VISUAL_APPENDIX_BG.md` (PARTS-DOC-01B). 01A остава авторитетният
източник на историческите snapshot/occurrence/artifact данни.

## Проучване и семантика преди миграцията

База: `78343f860dcce7417e33830b2adef74126d4ceea`.

1. Авторитетът е конкретният `PartCatalog.id`, проверен от backend, а не
   клиентският номер/описание. Нормалният writer е `POST /part-requests/multi`.
   Legacy writer-ът в `main.py` и unknown writer-ът нямат catalog binding.
2. Произходът се доказва чрез `source_record_key`, `source_id`, `source_row_index`,
   `source_version`, `revision`, `source_document_sha256` и verification полетата.
3. Има два действителни договора: директен `PartHotspot.part_id` и позиционен
   `PartCatalog.source_id = CatalogDiagram.source_id`,
   `PartCatalog.position = CatalogPositionHotspot.position`. Вторият е точната
   семантика на `catalog.service.diagram_hotspots`, не приблизително съвпадение.
   `CatalogPositionHotspot.diagram_id → CatalogDiagram.technical_document_id`
   и `PartHotspot.technical_document_id` определят визуалния документ.
4. Част може да има нула, една или много проверени области. Вземат се всички
   verified occurrences от двата договора. Непроверени области не се включват.
5. Повторенията са отделни редове/hotspot keys; различни source variants могат
   да сочат едни и същи позиционни области. Не се избира първата/най-близката.
6. Геометрията принадлежи на точни байтове, идентифицирани чрез SHA-256.
   Diagram hash трябва да съвпада с catalog source hash, когато последният е
   наличен. Директният hotspot може да сочи отделен документ.
7. Каталогът, схемите, областите и текущият `TechnicalDocument` са mutable.
8. `TechnicalDocumentRevision` има уникална версия, но content може да липсва
   и да остане само файлов път; няма обща DB гаранция за неизменимост. Затова
   съществуващият revision ID сам по себе си е недостатъчен.
9. Snapshot копира catalog identity/part metadata, verification, timestamp и
   origin, всички точни visual occurrences и source metadata. Историческите
   source IDs са стойности, без FK към изтриваемите live източници.
10. 01B ще използва snapshot ID/hash, подредените occurrences, точната страница,
    геометрията и съхранените source bytes. Няма нужда да чете live каталога.

## Избран модел

Един `PartVisualSnapshot` за един catalog binding на `PartRequestLine` (unique
FK към реда); `PartVisualOccurrence` за всяка област (unique snapshot/ordinal);
`PartVisualArtifact` с SHA-256 primary key и точните source bytes. Артефактът се
споделя между всички заявки. Съхранява се целият източник, а не изображение от
текущия renderer: това запазва точните PDF страници, без зависимост от версия
на rasterizer. Цената е еднократно съхранение на всеки използван source файл.

Не се архивират произволни файлове. Четенето използва само persisted document
content/revision или проверен файл в съществуващия technical-document storage.
Хешът се проверява при capture и download. Пътища не влизат в новия API;
документните имена се свеждат до filename, а произходът се пази чрез IDs/hash.
Липсващ/подменен източник на verified occurrence отказва цялата транзакция,
вместо да се представя като липсваща визуална връзка.

Подредбата е `(source kind, document ID, page, diagram ID, hotspot ID)`.
Ordinal е положителен и непроменим. Snapshot hash покрива schema version,
binding, capture timestamp/origin, catalog metadata и всички occurrences.
DB triggers забраняват update/delete на трите исторически таблици; броят на
occurrences и unique ordinal ограничават последващо дописване. FK към реда и
артефактите са restrict. Миграцията не създава исторически snapshots.

## Транзакции и съвместимост

Capture е преди единствения commit на създаването/изричното unknown свързване.
Общ service валидира catalog identity и създава snapshot; не commit-ва. При
неуспех request/line/link/snapshot/artifact/audit се връщат заедно. PostgreSQL
заключва canonical request при link; unique line snapshot и conflict-safe
artifact insert пазят конкурентните операции. Повторен link към същата част
е идемпотентен; различна част се отказва. Стар вече свързан ред без snapshot
остава исторически без snapshot — няма скрит backfill.

Unknown creation няма snapshot. При link origin е `CATALOG_LINK` и timestamp
е `linked_at`; оригиналните описание, снимка, бележка и история се запазват.
Нормалният origin е `REQUEST_CREATION`. Каталожен ред без области има snapshot
с празен списък и `no_visual_reference_at_capture`. Стар catalog-bound ред
без snapshot има `legacy_snapshot_unavailable`; manual/unknown/aggregate KIT
без binding има `no_catalog_binding`. COMPONENTS дава snapshot на всеки exact
catalog component; KIT няма единствена part identity и не измисля такава.

API е read-only и additive. Metadata следва `requests.view`; binary download
изисква и `documents.view`, както техническата библиотека. Документният snapshot
може да запише само immutable snapshot ID/hash. DOCX/PDF renderer-ите и
одобрените PART_REQUEST шаблони не получават визуално приложение в 01A.

Няма hard-coded HPWJ логика, brand/model/family/source version allowlist,
inventory IDs, известни страници или dataset counts в новия домейн. Бъдеща
машина/каталог с горните persisted relationships използва същия capture flow.
Синтетичните acceptance данни принадлежат само на изолирани QA fixtures.

## Схема и точен API договор

Миграция `20260920_0022`, след `20260826_0021`. Таблиците са
`part_visual_snapshots`, `part_visual_occurrences`, `part_visual_artifacts`.
Catalog identity (`catalog_part_id`, `source_id`, `source_record_key`) има отделни
индекси; dedicated `catalog` JSON е versioned immutable value object.
Source metadata на occurrence е аналогичен immutable value object, докато
ownership, ordinal, geometry, document/diagram identity и artifact FK са колони.
Двата JSON обекта не са полета на GeneratedDocument или OfficialDocumentVersion.
Хешът използва UTF-8 JSON, sorted keys, компактни separators, без NaN.

`PartRequestLine.visual_reference` и dedicated GET връщат `{state, snapshot}`.
`snapshot` има `id`, `sha256`, `schema_version=1`, `line_id`, `catalog_part_id`,
`source_id`, `source_record_key`, `captured_at` (naive ISO UTC), `capture_origin`,
`catalog`, `occurrence_count`, `visual_references`. Pydantic/OpenAPI схемите са
в `visual_schemas.py`. Липсващи source стойности остават `null`, без догадки.

Catalog value object: `source_row_index`, `source_version`,
`source_document_sha256`, `revision`, `verification_status`, `is_verified`,
`verified_by_id`, `verified_at`, `position`, `part_number`,
`replaced_by_part_number`, `requested_part_number`, `description`, `original_name`,
`manufacturer`, `brand`, `model`, `family`, `assembly`, `unit`, `source_document`
(само filename), `source_page`, `source_figure`, `diagram_page`.

Всяка occurrence: `ordinal`, `source_kind` (`PART_HOTSPOT`/`POSITION_HOTSPOT`),
`hotspot_id`, `technical_document_id`, `diagram_id`, `page_number`, `x`, `y`,
`width`, `height`, `artifact_sha256`, `source_metadata`. Metadata съдържа
`document_title`, `document_source_id`, `document_dataset_version`,
`document_revision`, `document_sha256`, `revision_id`, `revision_version`,
`revision_label`, `filename`, `media_type`, `byte_length`, `hotspot_key`, `label`,
`provenance`, `confidence`, `is_verified`, `verified_by_id`, `verified_at`,
`diagram_title`, `diagram_source_id`, `diagram_source_sha256`, `render_version`.
Историческите document/revision IDs са доказателствени стойности; гаранцията за
точни байтове е artifact FK/hash, дори при изтриване на live revision.

`PartCatalogImage` е отделна upload колекция без hotspot/diagram verification
договор; не се обявява автоматично за verified визуална позиция. 01A заснема
двата съществуващи verified hotspot договора. Snapshot не разчита на V2 manifest.

Audit записът (`part_visual_snapshot`) съдържа request reference, line/part IDs,
source identity, capture origin, брой области, snapshot hash и уникалните artifact
hash-ове. Binary data и пътища не се записват в новия audit.

Ново генерирани официални request snapshots добавят `visual_snapshot: {id, sha256}`
само за редове с вече съществуващ immutable snapshot. Старите document snapshots
не се променят; old/manual QA документите запазват предишния exact JSON договор.
Machine Passport, timeline, registry, reports, approvals, fulfillment, pending
counts и attachments продължават да използват същите request/line IDs и статуси.

При capture се проверява реалният page count и нормализираната геометрия.
Source SHA-256 се проверява преди content-addressed insert; конфликт по SHA
използва `ON CONFLICT DO NOTHING`, след което се сравняват действителните bytes.
Snapshot read проверява aggregate hash/count, download проверява source hash.
DB guards са приложение към обичайните права на инсталацията; собственикът на
базата остава доверен администратор, способен да променя самата схема.
