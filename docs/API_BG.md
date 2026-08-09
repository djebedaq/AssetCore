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
| `PUT` | `/api/users/me/profile` | потвърждава отделни имена, длъжност, отдел и законово изключение |
| `PUT` | `/api/users/{id}/profile` | scoped административно профилно обновяване; owner е защитен |
| `GET/POST` | `/api/owner`, `/api/owner/transfer` | owner designation и защитено прехвърляне с reauthentication |
| `GET` | `/api/owner/audit` | owner-only история на обозначението и прехвърлянията |
| `GET/POST` | `/api/license/status`, `/api/license/install` | офлайн Ed25519 проверка и owner-only инсталиране |
| `GET` | `/api/license/validate` | повторна криптографска проверка и enabled modules |
| `GET/POST` | `/api/external-signers` | отделни външни участници без User акаунт |
| `GET/POST` | `/api/official-documents` | неизменяеми официални документи и текущи версии |
| `GET` | `/api/official-documents/{id}/versions` | пълна история на версиите |
| `GET` | `/api/official-documents/{id}/versions/{v}/download/{docx|pdf}` | exact version download |
| `POST` | `/api/official-documents/{id}/participants` | заключва участниците и отваря подписването |
| `POST` | `/api/official-documents/{id}/prepare-for-signatures` | еквивалентен изричен prepare endpoint |
| `GET` | `/api/official-documents/{id}/preview/{docx\|pdf}` | preview на текущата version |
| `GET` | `/api/official-documents/{id}/signature-status` | signing progress и participant status |
| `POST` | `/api/official-documents/{id}/finalize` | идемпотентно потвърждава вече напълно подписана версия; иначе 409 |
| `GET` | `/api/official-documents/{id}/verify-hash` | проверява snapshot/DOCX/PDF SHA-256 |
| `POST` | `/api/official-documents/{id}/supersede` | нова коригираща версия с основание и нови подписи |
| `POST` | `/api/signatures/sessions` | еднократна, изтичаща подписна сесия |
| `GET/POST` | `/api/signing/{token}` | ограничено обобщение и подаване на ръчен графичен подпис |
| `POST` | `/api/signing/{token}/confirm` | окончателно потвърждение и status transition |
| `POST` | `/api/signing/{token}/reject` | отказ и затваряне на еднократната сесия |
| `GET` | `/api/signatures/{id}/image` | authenticated, private/no-store signature graphic |
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
| `POST` | `/api/repair-cases/{repair_id}/events` | проследимо събитие и разрешен stage transition |
| `POST/DELETE` | `/api/repair-cases/{repair_id}/participants...` | участници с DB защита срещу duplicate |
| `POST` | `/api/repair-cases/{repair_id}/parts` | използвана verified catalog част/проследим ред |
| `POST` | `/api/repair-cases/{repair_id}/attachments` | хеширано приложение към текущия ремонт |
| `POST` | `/api/repair-cases/{repair_id}/documents` | индивидуален ремонтен DOCX/PDF |
| `POST` | `/api/repair-cases/{repair_id}/documents/corrections` | нова заключена repair версия с задължително основание |
| `GET/POST` | `/api/part-requests/multi` | многоредови заявки за части |
| `POST` | `/api/part-requests/{id}/submit` | подава чернова за одобрение |
| `POST` | `/api/part-requests/{id}/decision` | проследимо решение от одобряващ |
| `PATCH` | `/api/part-requests/{id}/fulfillment` | поръчване, частична/пълна доставка или отказ с количества по редове |
| `POST` | `/api/part-requests/{id}/documents` | immutable Word/PDF версия на заявката |
| `POST` | `/api/part-requests/{id}/attachments` | добавя хеширано приложение към заявката |
| `GET` | `/api/part-request-attachments/{id}/download` | удостоверено изтегляне на приложение |
| `POST` | `/api/part-requests/unknown` | заявка за част без потвърден part number със снимка |
| `POST` | `/api/part-requests/{id}/lines/{line_id}/link-catalog-part` | административно свързване с потвърдена съвместима каталожна част |
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
| `POST` | `/api/document-template-versions/{id}/validate` | structural/hash/language/placeholder проверка |
| `GET` | `/api/generated-documents/{id}/download` | удостоверено изтегляне без вътрешен path |

`POST /api/transfers/bulk-issue` и `POST /api/transfers/bulk-return` връщат
`workflow_status=AWAITING_SIGNATURE`, `official_document_id` и последователни
`signing_tasks`. Машинното движение се прилага от backend едва след последния
потвърден подпис. `GET /api/signature-slots` е авторитетът за нужните позиции.
Manual `POST /api/official-documents` отказва `TRANSFER_ISSUE` и
`TRANSFER_RETURN` с HTTP 409, защото тези документи се създават само от transfer
workflow. Старият `POST /api/transfers` използва същия service слой, но новите
клиенти трябва да използват structured bulk договора, за да получат signing tasks.
При активен режим за лиценз и изтекъл grace всяка пишеща операция, освен
login/change-password и license install, връща HTTP `423` с
`code=license_read_only`; GET/export/backup достъпът остава.

## Потребители, роли и пароли

`GET /api/users` поддържа query параметри `search`, `role` и `is_active`. Основният administrator вижда всички акаунти. Director вижда само `mechanic` и `observer`; mechanic и observer получават HTTP 403. Отговорите никога не съдържат `password_hash`.

`POST /api/users` приема само:

```json
{
  "email": "<служебен-имейл>",
  "first_name": "<собствено-име>",
  "middle_name": "<бащино-име>",
  "last_name": "<фамилно-име>",
  "job_title": "<длъжност>",
  "department_id": "<department-id-или-null>",
  "role": "mechanic",
  "preferred_language": "bg",
  "temporary_password": "<временна-парола>",
  "confirm_password": "<същата-временна-парола>",
  "is_active": true
}
```

Трите отделни имена и длъжността са задължителни; `full_name` се генерира и не е източник на истина. Стандартният endpoint не приема `administrator`, `is_system_owner`, hash, timestamps или други защитени полета. Owner може да създава `director`, `mechanic` и `observer`; director — само `mechanic` и `observer`. Имейлът се нормализира, дублиран имейл връща 409, а невалидна роля, език или password policy — 422.

`PATCH /api/users/{id}` приема структурните identity полета, `department_id`, `role`, `preferred_language` и `is_active`; legacy `full_name` не заменя потвърдените отделни имена. За законово изключение се използва `PUT /api/users/{id}/profile` от administrator, който записва основание, одобрил и време. Self endpoint отказва самоодобрение с 403 `legal_name_exception_requires_admin`. За activation/deactivation използвайте и изричните action endpoints. Owner не се променя през нито един от тях; потребител не може да смени собствената си роля или да се деактивира.

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
  "location_id": "<location-id>",
  "usage_text": "<потвърдено-предназначение>",
  "condition_text": "<състояние-при-издаване>",
  "recipient": {
    "first_name": "<собствено-име>",
    "middle_name": "<бащино-име>",
    "last_name": "<фамилия>",
    "is_foreign_person": false,
    "name_exception_reason": null
  },
  "checklist": [
    {"code": "<код>", "condition": "GOOD", "note": null, "length_m": null}
  ],
  "document_language": "bg",
  "remarks": "<бележки>"
}
```

Старите свободни полета за фирма, отдел, кораб, док, кей, работна зона, комплектовка, шлангове, дюзи, пистолети и принадлежности не са част от активния bulk договор. `usage_text` се подава към съществуващото поле „Оборудването ще се използва за:“ в одобрения шаблон; generator/layout/template bytes не се променят. За HPWJ операции backend генерира официалния документ на `bg`, независимо от клиентска езикова настройка.

## Групово връщане

```json
{
  "document_language": "bg",
  "items": [
    {
      "transfer_id": "<active-transfer-id>",
      "machine_id": "<machine-id>",
      "condition_text": "<състояние-при-приемане>",
      "result_text": "<резултат-от-прегледа>",
      "checklist": [],
      "missing_equipment": null,
      "damage": null,
      "contamination": null,
      "notes": null,
      "next_status": "READY"
    }
  ]
}
```

`next_status` е само `READY` или `REPAIR`. Клиентът не подава return location; backend разрешава активния справочен запис с име `Цех` вътре в транзакцията. При `REPAIR` след финалните подписи се създава точно една ремонтна карта, свързана с transfer/document/return batch. Повторно връщане, грешен transfer, липсващ `Цех` или дублирана ремонтна връзка връщат HTTP 409 и не оставят частични промени.

`BatchProgressOut` включва `machine_numbers`. `BatchTransferOut` включва `issue_documents` и `return_documents`; до успешно приемане `return_documents` е празен масив. ZIP за return operation batch включва наличните финални issue и return DOCX/PDF файлове.

Основни transfer грешки: `issue_conflict`, `return_conflict`, `workshop_location_missing`, `return_repair_already_exists`, `machine_has_open_repair`, `repair_protocol_template_unavailable` и `repair_protocol_generation_failed`. Всички имат структуриран `code` и безопасно човешко съобщение.

Празен списък или повторен identifier връща HTTP 422. Липсваща машина връща 404. Активно предаване, неготов статус или concurrent uniqueness конфликт връща HTTP 409. Всички машини се заключват и валидират преди запис; при проблем не се създават партида, предавания или документи.

Успешният отговор съдържа `batch_id`, `batch_reference`, `transfers[]` с `transfer_id`, `protocol_number`, `machine_number`, индивидуални документи и `zip_download_endpoint`.

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

## Аварийна административна процедура

- `GET /api/emergency-access/status` — видим за всеки активен удостоверен
  потребител статус без чувствителното основание;
- `POST /api/emergency-access/start` — owner administrator, текуща парола,
  основание и `duration_minutes` от 5 до 60; връща 201;
- `POST /api/emergency-access/{session_id}/end` — защитено предсрочно
  приключване с повторна парола и основание.

Повторен старт връща 409. Невалидно повторно удостоверяване или чужд owner връща
403. Процедурата не създава нова роля, не променя permission матрицата и не е
backdoor. Всички успешни и отхвърлени опити се одитират.

## Ремонтни преходи и completion gate

Допустимата последователност е `ACCEPTED → DIAGNOSIS → WAITING_APPROVAL / WAITING_PARTS / REPAIRING → TESTING → COMPLETED`. `WAITING_APPROVAL` и `WAITING_PARTS` са optional branches. `PATCH` записва подадените полета и по желание `status`; важните изисквания се оценяват в същата транзакция след row lock на PostgreSQL.

- към `DIAGNOSIS`: `reported_problem` и `condition_before`;
- към `WAITING_*`/`REPAIRING`: `diagnosis`, `required_work`, `diagnosis_minutes`;
- към `TESTING`: `work_performed`, `repair_minutes` и завършено изискано почистване;
- към `COMPLETED`: успешен задължителен тест, `test_details`, `result`, `condition_after`, `testing_minutes` и всички completion gates.

Невалиден преход или липсваща стъпка връща HTTP 409 с `detail.code=repair_stage_requirements_missing` или конкретен completion code и човешки `detail.message` на български. Отказът не оставя променени полета, статус или документ. Успешният `COMPLETED` записва DOCX/PDF, approver, repair/machine events, `machine.status=READY` и активното местоположение `Цех` в една транзакция.

`POST /participants` приема `user_id` или `full_name`, `job_title` и `contribution`. Нормализираният identity key е уникален в рамките на ремонта; повторение и едновременен double submit връщат HTTP 409 с `repair_participant_already_exists`. `POST /parts` разрешава verified catalog reference и пази каталожния номер, количество, мярка и provenance snapshot. След `COMPLETED` participant/part/attachment mutations са заключени.

## Файлове и версии

Upload endpoint-ите приемат base64 content, ограничен размер, безопасно име и whitelist media type. Сървърът записва SHA-256. Нов revision или повторно генериране създава нов immutable запис (`-V2`, `-V3`), без overwrite на по-стар документ. Download отговорът съдържа само безопасно име и payload — никога вътрешна файлова система.

## Административни справочници

Създаването и промяната на местоположение/отдел изисква `settings.manage`, предоставен само на administrator. Дубликат връща HTTP 409 със стабилен `location_duplicate` или `department_duplicate`. `PATCH` променя само подадените полета. `is_active=false` не изтрива записа и не променя историческите връзки; формите не предлагат неактивен запис за нов избор, но продължават да показват вече използвана стойност. Всяко действие създава audit запис.
