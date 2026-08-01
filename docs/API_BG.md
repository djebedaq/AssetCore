# AssetCore API

Интерактивната OpenAPI документация е достъпна на `/docs`, а схемата — на `/openapi.json`. Всички описани endpoints, освен `/api/health` и `/api/auth/login`, изискват Bearer token. Авторизацията използва централизирани permission кодове; ролите са точно `administrator`, `director`, `mechanic` и `observer`. Издаване и връщане изискват съответно `transfers.create` и `transfers.return`.

## Основни endpoints

| Метод | Endpoint | Резултат |
|---|---|---|
| `GET` | `/api/auth/me` | безопасен текущ профил, owner знак и permission кодове |
| `POST` | `/api/auth/change-password` | проверява текущата и задава новата парола; връща нов token |
| `GET/POST` | `/api/users` | scoped списък/създаване на потребители |
| `GET/PATCH` | `/api/users/{user_id}` | scoped профил и разрешени промени |
| `POST` | `/api/users/{user_id}/activate` | активира акаунт и обезсилва старите му токени |
| `POST` | `/api/users/{user_id}/deactivate` | деактивира акаунт без изтриване на историята |
| `POST` | `/api/users/{user_id}/reset-password` | задава временна парола и задължителна смяна |
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
| `GET` | `/api/departments` | справочни отдели за роли с `documents.view` |
| `GET` | `/api/admin/reference-data` | местоположения и отдели, включително неактивни записи |
| `POST/PATCH` | `/api/admin/locations...` | създаване и активиране/деактивиране на местоположения |
| `POST/PATCH` | `/api/admin/departments...` | триезични отдели и активност |
| `POST` | `/api/admin/import-preview` | signed preview без запис |
| `POST` | `/api/admin/import-confirm` | потвърждава непроменен валиден preview |
| `GET/POST` | `/api/document-templates` | шаблони и версии |
| `POST` | `/api/document-templates/{id}/versions` | качва защитен DOCX/PDF като непубликувана версия |
| `GET` | `/api/document-template-versions/{id}/download` | administrator download на проверявания изходен файл |
| `POST` | `/api/document-template-versions/{id}/publish` | публикува версия само за езика ѝ |
| `GET` | `/api/generated-documents/{id}/download` | удостоверено изтегляне без вътрешен path |

Старият `POST /api/transfers` остава съвместим и използва същия защитен service слой за единично издаване/връщане.

## Потребители, роли и пароли

`GET /api/users` поддържа query параметри `search`, `role` и `is_active`. Основният administrator вижда всички акаунти. Director вижда само `mechanic` и `observer`; mechanic и observer получават HTTP 403. Отговорите никога не съдържат `password_hash`.

`POST /api/users` приема само:

```json
{
  "email": "<служебен-имейл>",
  "full_name": "<име>",
  "role": "mechanic",
  "preferred_language": "bg",
  "temporary_password": "<временна-парола>",
  "confirm_password": "<същата-временна-парола>",
  "is_active": true
}
```

Стандартният endpoint не приема `administrator`, `is_system_owner`, hash, timestamps или други защитени полета. Owner може да създава `director`, `mechanic` и `observer`; director — само `mechanic` и `observer`. Имейлът се нормализира, дублиран имейл връща 409, а невалидна роля, език или password policy — 422.

`PATCH /api/users/{id}` приема само `full_name`, `role`, `preferred_language` и `is_active`. За activation/deactivation използвайте и изричните action endpoints. Owner не се променя през нито един от тях; потребител не може да смени собствената си роля или да се деактивира.

`POST /api/users/{id}/reset-password` приема `temporary_password` и `confirm_password`. Успехът задава `must_change_password = true`, променя token version и не връща паролата. До `POST /api/auth/change-password` всички работни permission dependencies връщат 403 `password_change_required`. Успешната смяна връща нов Bearer token и безопасен профил.

Основни structured errors:

| HTTP | `code` | Значение |
|---:|---|---|
| 403 | `permission_denied` | липсва изискван permission |
| 403 | `user_scope_denied` | director опитва да управлява director/administrator |
| 403 | `role_escalation_denied` | опит за неразрешена роля |
| 403 | `system_owner_protected` | опит за промяна на основния администратор |
| 403 | `password_change_required` | временната парола трябва първо да бъде сменена |
| 409 | `duplicate_email` | нормализираният имейл вече съществува |
| 422 | `password_policy` / `validation_error` | невалидни входни данни |

Password policy: минимум 10 знака, поне една малка и главна буква, цифра и специален знак, без съвпадение със служебния имейл и без очевидно слаба стойност. Пароли, hash-ове и tokens не се включват в API или audit payload-и.

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

Новата версия приема `language`, проверен `filename`/`media_type`/`content_base64`, `layout_contract`, `effective_from`, `effective_to`, `required_fields`, `numbering_rule`, `department` и задължително `change_note`. Тя остава чернова. Само administrator с `templates.manage` може отделно да я изтегли за проверка и да извика publish endpoint-а. При генериране backend-ът избира само публикувана версия за точния език, чийто период на валидност е активен; иначе връща HTTP 409 `document_template_unavailable` и цялата бизнес операция се отменя.

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

- `administrator`: пълен достъп; основният owner управлява директорите и критичната конфигурация;
- `director`: широк оперативен достъп, издаване/връщане, ремонти, одобрение, протоколи, оперативен audit и mechanic/observer accounts;
- `mechanic`: издаване/връщане, ремонти, технически документи и създаване на заявки без одобрение;
- `observer`: само ограничен регистър, търсене, текущ статус, местоположение и наличност.

Backend-ът е авторитетен за тези права. Скриването или деактивирането на действия във frontend-а е само допълнителна защита на интерфейса.

## Ремонтни преходи и completion gate

Допустимата последователност е `ACCEPTED → DIAGNOSIS → WAITING_APPROVAL / WAITING_PARTS / REPAIRING → TESTING → COMPLETED`. `COMPLETED` изисква преглед, изпълнено задължително почистване, описание на работата, успешен задължителен тест и резултат. Невалиден преход или липсваща стъпка връща HTTP 409 със стабилен `code` и Bulgarian `message`.

## Файлове и версии

Upload endpoint-ите приемат base64 content, ограничен размер, безопасно име и whitelist media type. Сървърът записва SHA-256. Нов revision или повторно генериране създава нов immutable запис (`-V2`, `-V3`), без overwrite на по-стар документ. Download отговорът съдържа само безопасно име и payload — никога вътрешна файлова система.

## Административни справочници

Създаването и промяната на местоположение/отдел изисква `settings.manage`, предоставен само на administrator. Дубликат връща HTTP 409 със стабилен `location_duplicate` или `department_duplicate`. `PATCH` променя само подадените полета. `is_active=false` не изтрива записа и не променя историческите връзки; формите не предлагат неактивен запис за нов избор, но продължават да показват вече използвана стойност. Всяко действие създава audit запис.
