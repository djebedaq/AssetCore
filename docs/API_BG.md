# AssetCore API

Интерактивната OpenAPI документация е достъпна на `/docs`, а схемата — на `/openapi.json`. Всички описани endpoints, освен `/api/health` и `/api/auth/login`, изискват Bearer token. Операциите за издаване и връщане изискват роля `admin` или `manager`.

## Основни endpoints

| Метод | Endpoint | Резултат |
|---|---|---|
| `GET` | `/api/auth/me` | текущ потребител, роля и предпочитан език |
| `PATCH` | `/api/users/me/preferences` | записва `preferred_language`: `bg`, `en` или `ru` |
| `GET` | `/api/transfers/availability` | наличност и причина за недостъпност за всяка машина |
| `POST` | `/api/transfers/bulk-issue` | атомарно групово издаване, HTTP 201 |
| `POST` | `/api/transfers/bulk-return` | атомарно пълно или частично връщане, HTTP 200 |
| `GET` | `/api/transfer-batches` | партиди и обобщен прогрес |
| `GET` | `/api/transfer-batches/{batch_id}` | партида, индивидуални предавания и документи |
| `GET` | `/api/transfer-batches/{batch_id}/progress` | общо, върнати и все още издадени машини |
| `GET` | `/api/protocol-documents/{document_id}/download` | удостоверено изтегляне на индивидуален DOCX/PDF |
| `GET` | `/api/transfer-batches/{batch_id}/documents.zip` | всички протоколи от партидата в ZIP |
| `GET` | `/api/machines/{machine_id}/passport` | цифров паспорт, custom полета и свързана история |
| `PUT` | `/api/machines/{machine_id}/custom-fields` | атомарно обновява валидирани category полета |
| `POST` | `/api/machines/{machine_id}/attachments` | качва проверен файл със SHA-256 |
| `GET/POST` | `/api/repair-cases` | списък и приемане за преглед/ремонт |
| `PATCH` | `/api/repair-cases/{repair_id}` | валидиран ремонтен преход и completion gates |
| `POST` | `/api/repair-cases/{repair_id}/documents` | индивидуален ремонтен DOCX/PDF |
| `GET/POST` | `/api/part-requests/multi` | многоредови заявки за части |
| `POST` | `/api/part-requests/{id}/submit` | подава чернова за одобрение |
| `POST` | `/api/part-requests/{id}/decision` | проследимо решение от одобряващ |
| `PATCH` | `/api/part-requests/{id}/fulfillment` | поръчване, частична/пълна доставка или отказ с количества по редове |
| `POST` | `/api/part-requests/{id}/documents` | immutable Word/PDF версия на заявката |
| `POST` | `/api/part-requests/{id}/attachments` | добавя хеширано приложение към заявката |
| `GET` | `/api/part-request-attachments/{id}/download` | удостоверено изтегляне на приложение |
| `GET/POST` | `/api/catalog/parts` | проверим каталог с provenance |
| `POST` | `/api/catalog/parts/{id}/verify` | човешко потвърждение на каталожна част |
| `GET/POST` | `/api/catalog/parts/{id}/images` | списък/качване на проверено каталожно изображение |
| `GET` | `/api/catalog/part-images/{id}/download` | удостоверено изтегляне на каталожно изображение |
| `GET/POST` | `/api/catalog/parts/{id}/hotspots` | визуални позиции върху технически документ |
| `GET` | `/api/catalog/hotspots?technical_document_id=...&page_number=...` | всички позиции върху конкретна страница |
| `POST` | `/api/catalog/hotspots/{id}/verify` | човешко потвърждение на визуална позиция |
| `GET/POST` | `/api/repair-kits` | проследими ремонтни комплекти |
| `GET/POST` | `/api/technical-library` | филтрирана, версионирана техническа библиотека |
| `POST` | `/api/technical-library/{id}/revisions` | добавя нова версия без подмяна на старата |
| `GET` | `/api/search?q=...` | групирано глобално търсене |
| `GET/POST/PATCH` | `/api/admin/users...` | потребители, роли и активност |
| `GET` | `/api/departments` | достъпни справочни отдели за удостоверени потребители |
| `GET` | `/api/admin/reference-data` | местоположения и отдели, включително неактивни записи |
| `POST/PATCH` | `/api/admin/locations...` | създаване и активиране/деактивиране на местоположения |
| `POST/PATCH` | `/api/admin/departments...` | триезични отдели и активност |
| `POST` | `/api/admin/import-preview` | signed preview без запис |
| `POST` | `/api/admin/import-confirm` | потвърждава непроменен валиден preview |
| `GET/POST` | `/api/document-templates` | шаблони и версии |
| `POST` | `/api/document-templates/{id}/versions` | качва защитен DOCX/PDF като непубликувана версия |
| `GET` | `/api/document-template-versions/{id}/download` | admin download на проверявания изходен файл |
| `POST` | `/api/document-template-versions/{id}/publish` | публикува версия само за езика ѝ |
| `GET` | `/api/generated-documents/{id}/download` | удостоверено изтегляне без вътрешен path |

Старият `POST /api/transfers` остава съвместим и използва същия защитен service слой за единично издаване/връщане.

## Групово издаване

Полето `machine_ids` съдържа вътрешните идентификатори, получени от `/api/machines` или `/api/transfers/availability`. Следващият пример е схема; заместете означенията с реални IDs от API и не ги приемайте за бизнес данни.

```json
{
  "machine_ids": ["<machine-id-1>", "<machine-id-2>"],
  "company_unit": "<звено>",
  "department": "<отдел>",
  "vessel": "<обект>",
  "dock": "<док>",
  "pier": "<кей>",
  "work_area": "<работна зона>",
  "location_text": "<място на работа>",
  "location_id": "<location-id>",
  "handed_over_by": "<предал>",
  "accepted_by": "<приел>",
  "equipment": "<комплектовка>",
  "hoses": "<шлангове>",
  "nozzles": "<дюзи>",
  "guns": "<пистолети>",
  "accessories": "<принадлежности>",
  "condition_text": "<състояние>",
  "remarks": "<бележки>"
}
```

Празен списък или повторен identifier връща HTTP 422. Липсваща машина връща 404. Активно предаване, неготов статус или concurrent uniqueness конфликт връща HTTP 409. Всички машини се заключват и валидират преди запис; при проблем не се създават партида, предавания или документи.

Успешният отговор съдържа `batch_id`, `batch_reference`, `transfers[]` с `transfer_id`, `protocol_number`, `machine_number`, индивидуални документи и `zip_download_endpoint`.

## Групово връщане

Всеки `items[]` запис съдържа едновременно `transfer_id` и `machine_id`. Тази двойка предотвратява връщане през грешна история.

```json
{
  "items": [
    {
      "transfer_id": "<active-transfer-id>",
      "machine_id": "<matching-machine-id>",
      "condition_text": "<състояние при връщане>",
      "result_text": "<резултат от приемането>",
      "notes": "<индивидуални бележки>",
      "missing_equipment": "<липсващо оборудване>",
      "damage": "<повреди>",
      "contamination": "<замърсяване>",
      "cleaning_required": true,
      "inspection_required": true,
      "repair_required": false,
      "returned_by": "<върнал>",
      "accepted_by": "<приел>",
      "location_id": "<location-id>",
      "next_status": "INSPECTION"
    }
  ]
}
```

Допустимите следващи етапи са техническите кодове `RETURNED`, `INSPECTION`, `CLEANING`, `REPAIR`, `WAITING_APPROVAL`, `WAITING_PARTS` и `TESTING`. Директно `READY` не се приема. Българските legacy стойности остават входно съвместими, но новите интеграции трябва да използват кодовете. Една заявка е атомарна, но може умишлено да съдържа само част от машините в партидата; останалите индивидуални предавания остават активни.

## Шаблони и официални документи

Новата версия приема `language`, проверен `filename`/`media_type`/`content_base64`, `layout_contract`, `effective_from`, `effective_to`, `required_fields`, `numbering_rule`, `department` и задължително `change_note`. Тя остава чернова. Само admin може отделно да я изтегли за проверка и да извика publish endpoint-а. При генериране backend-ът избира само публикувана версия за точния език, чийто период на валидност е активен; иначе връща HTTP 409 `document_template_unavailable` и цялата бизнес операция се отменя.

## Изпълнение на заявка за части

`PATCH /api/part-requests/{id}/fulfillment` приема статус `ORDERED`, `PARTIALLY_DELIVERED`, `DELIVERED` или `CANCELLED`, доставчик, бележка и `lines[]` с `line_id` и натрупано `delivered_quantity`. Количеството не може да намалява или да надвишава заявеното. `DELIVERED` изисква всички редове да са изпълнени, а всяка промяна се записва в одита.

## Структурирани грешки

Бизнес конфликтите използват следния общ формат:

```json
{
  "detail": {
    "code": "machine_already_issued",
    "message": "<ясно съобщение на български>",
    "conflicts": [
      {
        "machine_number": "<номер>",
        "status": "<статус>",
        "protocol_number": "<активен протокол>",
        "batch_reference": "<партида>",
        "issued_at": "<дата или null>",
        "current_recipient_or_location": "<получател/място или null>"
      }
    ]
  }
}
```

Кодове: HTTP 401 без валиден token, 403 без изискваната роля, 404 за липсващ ресурс, 409 за бизнес конфликт и 422 за невалидна структура/полета. Validation отговорите са нормализирани до `validation_error`, локализирано `message` според `Accept-Language` и безопасен списък `errors`; сурови request данни и вътрешни пътища не се връщат.

## Ролеви граници

- `admin`: пълен оперативен достъп;
- `manager`: издаване и връщане;
- `mechanic`: ремонти и заявки за части;
- `approver`: преглед на audit историята;
- `viewer`: read-only достъп, включително audit, без мутации.

Backend-ът е авторитетен за тези права. Скриването или деактивирането на действия във frontend-а е само допълнителна защита на интерфейса.

## Ремонтни преходи и completion gate

Допустимата последователност е `ACCEPTED → DIAGNOSIS → WAITING_APPROVAL / WAITING_PARTS / REPAIRING → TESTING → COMPLETED`. `COMPLETED` изисква преглед, изпълнено задължително почистване, описание на работата, успешен задължителен тест и резултат. Невалиден преход или липсваща стъпка връща HTTP 409 със стабилен `code` и Bulgarian `message`.

## Файлове и версии

Upload endpoint-ите приемат base64 content, ограничен размер, безопасно име и whitelist media type. Сървърът записва SHA-256. Нов revision или повторно генериране създава нов immutable запис (`-V2`, `-V3`), без overwrite на по-стар документ. Download отговорът съдържа само безопасно име и payload — никога вътрешна файлова система.

## Административни справочници

Създаването и промяната на местоположение/отдел изисква `admin`. Дубликат връща HTTP 409 със стабилен `location_duplicate` или `department_duplicate`. `PATCH` променя само подадените полета. `is_active=false` не изтрива записа и не променя историческите връзки; формите не предлагат неактивен запис за нов избор, но продължават да показват вече използвана стойност. Всяко действие създава audit запис.
