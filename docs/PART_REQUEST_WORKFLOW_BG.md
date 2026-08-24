# Каноничен workflow за заявени части

## State machine и отговорности

AssetCore съхранява стабилни технически статуси и ги превежда само в API/UI слоя:

`DRAFT → WAITING_APPROVAL → APPROVED → ORDERED → PARTIALLY_DELIVERED → DELIVERED`

Разрешените отклонения са:

- `WAITING_APPROVAL → REJECTED`;
- `WAITING_APPROVAL → DRAFT` при връщане за промени;
- `APPROVED | ORDERED | PARTIALLY_DELIVERED → CANCELLED`;
- `ORDERED → DELIVERED` при действително изпълнени всички количества;
- `PARTIALLY_DELIVERED → PARTIALLY_DELIVERED | DELIVERED` според натрупаните доставки.

| Преход | Канонична функция | API | Permission | Audit | Документен ефект |
|---|---|---|---|---|---|
| създаване на чернова | валидацията и persistence-ът на `create_multi_part_request` | `POST /api/part-requests/multi` | `requests.create` | създадена заявка, машина, редове, verified catalog IDs | няма |
| `DRAFT → WAITING_APPROVAL` | `part_requests.submit_for_approval` | `POST /api/part-requests/{id}/submit` | `requests.create` | предишен/нов статус, редове и actor | няма |
| catalog create + submit | същият `submit_for_approval`, извикан преди единствения commit | `POST /api/part-requests/multi` с `submit_for_approval=true` | `requests.create` | create и submit в същата транзакция | няма |
| решение | `part_requests.decide_request` | `POST /api/part-requests/{id}/decision` | `requests.approve` | решение, предишен/нов статус, actor и approval history | няма автоматично генериране |
| поръчване/доставка/отказ | валидираният fulfillment transition | `PATCH /api/part-requests/{id}/fulfillment` | `requests.create` | статус, доставчик и количества преди/след | няма |
| официален протокол | `make_part_request_documents` и official registry registration | `POST /api/part-requests/{id}/documents` | `documents.generate` | document number, език и generated IDs | отделни DOCX/PDF и immutable official version |

Production PostgreSQL заключва съществуващия request row при submit, decision и fulfillment. SQLite използва една транзакция и съвместимото локално serialized write поведение. Домейн функциите не извършват `commit`; API route-ът е собственик на транзакцията.

## Създаване само от каталога

Новата потребителска операция започва само от „Каталог резервни части“ чрез точни избрани verified части, потвърден repair kit и текущата количка. Финалното действие изпраща `submit_for_approval=true`; заявката и редовете се създават и преминават към `WAITING_APPROVAL` с един commit. Ако transition, audit или persistence откаже, сесията се връща и не остава orphan `DRAFT`.

Старите API записи и historical `DRAFT` не се изтриват. Разделът „Заявени части“ ги показва и предлага само каноничното действие „Подай за одобрение“ на потребител с `requests.create`; той не предлага нов create flow.

## Action-required badge

`GET /api/part-requests/pending-action-count` е каноничният източник. Той връща броя на `WAITING_APPROVAL` само когато текущият потребител има `requests.approve`; останалите потребители с право за преглед получават нула. Отваряне или преглед не променя броя и няма `seen` поле. Клиентът валидира отново при вход, refresh, route change, focus/връщане към приложението и след workflow действие.

## Официални документи

Официален „Протокол за заявка за части“ се създава само след `APPROVED` (или последващ fulfillment статус). Генерираните DOCX/PDF и `OfficialDocumentVersion` пазят canonical number, template/version/hash, actor, request/machine IDs, reason и точните редове с `catalog_part_id`, Part No., количество и provenance. Повторното разрешено генериране създава следващ version suffix и не презаписва историята.
