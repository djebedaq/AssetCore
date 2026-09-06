# ASSET-03A — read-only хронология на машината

## Обхват и архитектура

База: `dbb144e8e2196d4995c7e400ba26a4093f372314` — merged ASSET-02.
Новият `GET /api/machines/{machine_id}/timeline` агрегира съществуващи факти.
Той не създава нов бизнес процес, таблица за събития или заместител на audit log.
Не променя `/passport`, неговото `history`, frontend, роли, документи или подписи.
**ASSET-03B UI НЕ Е ИМПЛЕМЕНТИРАН.**

`assets/routes.py` е тънкият HTTP adapter; `assets/timeline.py` събира фактите;
`timeline_schemas.py` дефинира типизирания отговор; `timeline_details.py` притежава
само безопасните, специфични за тази хронология projections.
`official_documents/registry.py::machine_official_document_metadata` използва
същите machine-scoped candidates, grouping и canonical-over-legacy правила като
ASSET-02/DOCS-01. Не зарежда подписи или съдържание на файлове.

## API договор

Permission: съществуващото `assets.view`, със същата authentication/session граница.
Administrator, director и mechanic имат оперативната хронология. Observer получава
`limited_view=true`, празни `items`, `total=count=total_pages=0` и двата navigation
флага `false`; проверява се само съществуването на машината. Не се извличат скрити
бройки, документи, заявки, ремонти или audit записи.

| Query | По подразбиране | Валидация |
|---|---|---|
| `page` | 1 | цяло число ≥ 1 |
| `page_size` | 50 | цяло число 1–100 |
| `category` | `all` | `all`, `asset`, `transfer`, `repair`, `parts`, `document` |

Отговор: `machine_id`, `limited_view`, `category`, `total`, `count`, `page`,
`page_size`, `total_pages`, `has_previous`, `has_next`, `items`.
`total` е **след** дедупликация и category филтър, а `count` е размерът на страницата.
Страница над последната връща 200 с празни `items`, без измислени placeholders.
Невалидни query параметри връщат 422; липсваща машина — съществуващото 404
„Машината не е намерена.“; неудостоверен достъп — 401.

Всеки item съдържа:

- `event_key`: стабилна identity на съществуващия факт;
- `category`, `event_type`: технически кодове, без нови преведени UI labels;
- `occurred_at`: реален timestamp от източника, никога време на GET заявката;
- `reference`: записана референция, без изчислени суфикси за липсващи протоколи;
- `source_type`, `source_id`: типизиран източник и неговият вътрешен ID;
- `status_before`, `status_after`, `description`: nullable, само записани факти
  или изричното значение на канонична операция (например issued → ISSUED);
- `machine_id` и `related` с nullable `transfer_id`, `repair_id`,
  `part_request_id`, `official_document_id`;
- `details`: allowlisted scalar metadata, не произволен JSON snapshot.

OpenAPI описва пълния response schema. Примерни заявки (заместете placeholder-а
с реалния вътрешен ID от `/api/machines`; това не са бизнес записи):

```text
GET /api/machines/{machine_id}/timeline
GET /api/machines/{machine_id}/timeline?category=repair&page=1&page_size=25
GET /api/machines/{machine_id}/timeline?category=document&page=2&page_size=10
```

## Проверени източници и приоритет

| Семейство | Авторитет и дата | Дедупликация / резервен източник |
|---|---|---|
| Asset/master data | `MachineEvent.created_at`, exact `machine_id` | Само известни asset кодове: MACHINE_CREATED/UPDATED, CUSTOM_FIELDS_UPDATED, ATTACHMENT_ADDED, IMPORTED и location събития. Няма синтетично събитие от `Machine.updated_at`. |
| Издаване | `TransferProtocol.issued_at` + `issue_status=COMPLETED` | Едно `transfer:{id}:issued`; съответстващо TRANSFER_ISSUED MachineEvent не се повтаря. |
| Заявено връщане | `TransferProtocol.return_requested_at` | `transfer:{id}:return_requested`; **не** означава връщане или промяна на машинен статус. |
| Реално връщане | `returned_at` **и** `return_status=COMPLETED` | `transfer:{id}:returned`; inactive, документ или pending/cancelled state сами по себе си не доказват приключване. |
| Ремонт | `RepairEvent.created_at`, exact repair→machine | Реалният код/статуси/описание на всеки event. REPAIR_ACCEPTED/STATUS_CHANGED/REPAIR_EVENT от MachineEvent се потискат само при представен съответстващ факт. |
| Ремонт без начално/крайно event | `Repair.opened_at`; `closed_at` + `status=COMPLETED` | REPAIR_OPENED само без ACCEPTED/RETURN_DIRECTED_TO_REPAIR. REPAIR_COMPLETED само без COMPLETED event или реален event преход към COMPLETED. |
| Използвани части | PART_ADDED RepairEvent; иначе `RepairPart.created_at` | PART_ADDED е в `parts`. При липса на съответстващ event се показва PART_USED, без промяна на количеството. |
| Заявки | `created_at`, `submitted_at`, `ordered_at`, `delivered_at` | Отделни реално датирани milestones, без реконструкция от `updated_at`/текущ статус. |
| Решения | `PartRequestApproval.decided_at` | APPROVED / REJECTED / RETURNED_FOR_CHANGES са отделни решения с ID; повторните решения не се сливат. Само historical ред без approvals допуска explicit `decided_at` + APPROVED/REJECTED state fallback. |
| Частична доставка/отмяна | Тясно ограничен `AuditLog.created_at` | Само exact `entity_type=part_request`, scoped `entity_id`, action „Обновено изпълнение на заявка за части“ и валиден explicit previous_status/new_status за PARTIALLY_DELIVERED/CANCELLED. |
| Документи | Текуща `OfficialDocumentVersion.finalized_at`, иначе version/document creation | Един current-version event; същите canonical-over-legacy правила, DOCX/PDF са един документ, не два факта. Реалните legacy-only записи остават. |

### Точна връзка и legacy ограничения

Всички машинни/transfer/repair заявки са с numeric `machine_id`. Заявки за части
се включват по direct machine ID или **само при NULL direct ID** по repair→machine.
Документите използват съществуващите direct machine/transfer и точни snapshot
repair/request IDs; новият metadata helper разрешава и historical NULL-machine
request→repair връзка чрез предварително scoped ID set. Default registry/passport
scope не е променен. Не се прави търсене на „4“ в „14“, filename или свободен текст.

MachineEvent fallback се запазва, когато съществува действителен исторически
event, но липсва възстановим domain milestone. Съпоставянето е по ID или точно
равенство на reference **вече вътре в една машина**, не по substring. Pending или
cancelled canonical операция не може да бъде преобявена за завършена от fallback.
Източникът остава `machine_event`, а не подправен каноничен transfer/repair.

Текущият PART_ADDED writer не записва `repair_part_id`. Дедупликацията използва
пълното равно множество от записани part metadata + описание + actor, с подредено
one-to-one съпоставяне след `RepairPart.created_at`. Един event не може да скрие
два RepairPart реда. При различни данни редът се запазва като PART_USED, не се
поправя или конвертира. Няма fuzzy каталожно съпоставяне.

Не се измисля timestamp за историческа отмяна без валиден transition запис.
При cancellation текущият transfer workflow изчиства `return_requested_at`;
този read API не възстановява изтритото поле с догадки. Не се претендира за пълен
архив на всички минали версии: документният milestone представлява текущата
канонична версия; старите версии/подписи остават в съществуващата документна история.

## Безопасно представяне и права

Никога не се връщат raw audit details, signature/session payloads, изображения,
DOCX/PDF bytes, пълни snapshots, password/token/key полета, hashes или storage paths.
`details` има отделен allowlist за всяка event family. Nested JSON не преминава.
Оперативни descriptions/notes остават допустими; encoded payloads, credentials и
absolute internal paths се отхвърлят и от тези display полета.
PARTIALLY_DELIVERED/CANCELLED fallback е само безопасна domain projection,
**не** достъп до audit feed и не разширява `audit.view_operational` за mechanic.
Security/governance/login/license audit никога не се включва.

## Подреждане, заявки и read-only гаранции

Първо се събират exact machine-scoped факти, прилагат се приоритетите/дедупликацията,
след това category филтър, общо сортиране и чак накрая pagination.
Sort е descending по `(occurred_at UTC, source rank, source_id, event rank, event_key)`.
Source rank (ascending): machine_event, transfer, repair, repair_event, repair_part,
part_request, part_request_approval, part_request_transition, protocol_document,
generated_document, official_document. При еднакъв source ID request milestones
са created→submitted→decision→ordered→partial→delivered→cancelled; transfer milestones
са issued→return_requested→returned. Крайният key е последен deterministic tie-breaker.

Използва се bounded **per-machine** агрегация в паметта, не global lifecycle feed.
Няма N+1 relationship hydration; SQLAlchemy `raiseload` пази domain query границите.
Документните candidates използват съществуващия bounded-by-document-type metadata
scan за portable JSON snapshot връзките; не зареждат binaries/signatures.
Това е умишлено ограничение на сегашната архитектура, не SQL keyset pagination.
При много голяма история бъдеща измерена оптимизация може да въведе SQL pagination
само ако запази глобалния post-deduplication ordering договор.

Service-ът използва `no_autoflush`, няма `add`, `flush`, `commit`, update/delete,
backfill, генератор или audit writer. Тестовете сравняват fingerprint на **всички
колони, pointers, bytes и hashes** на свързаните domain/history/document таблици,
проверяват `new/dirty/deleted` и забраняват autoflush дори при caller pending промяна.

## Регресионно покритие

`tests/test_machine_lifecycle_timeline.py` покрива HTTP contract, всички категории,
етапите/дедупликацията, действителния issue/sign/return writer, read-only, Observer,
malformed/sensitive metadata, стабилни ключове, pagination и exact машина 4 срещу 14.
Query-count тестът сравнява малък scenario с още 30 ремонта/документа, без увеличение
на броя SQL заявки и без binary/signature hydration.

`tests/postgres/test_machine_lifecycle_timeline_postgres.py` използва **съществуващия**
`pg_factory` и migrated disposable PostgreSQL schema. Споделеният test-only scenario
има изрично очаквани ключове/хронология и се изпълнява отделно и върху SQLite.
Проверява exact linkage, canonical-over-legacy, issue-only без fake return,
RepairEvent, заявки/решения, used parts, tie order, category pagination и read-only.
GitHub `postgres` job го изпълнява автоматично чрез `pytest tests/postgres`.

Няма нова Alembic revision, редактирана migration, production seed/source/catalog
промяна, document regeneration или frontend промяна. PR остава за review; не се merge-ва.
