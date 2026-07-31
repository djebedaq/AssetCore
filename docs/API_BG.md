# AssetCore API — групови предавания

Интерактивната OpenAPI документация е достъпна на `/docs`, а схемата — на `/openapi.json`. Всички описани endpoints, освен `/api/health` и `/api/auth/login`, изискват Bearer token. Операциите за издаване и връщане изискват роля `admin`.

## Основни endpoints

| Метод | Endpoint | Резултат |
|---|---|---|
| `GET` | `/api/transfers/availability` | наличност и причина за недостъпност за всяка машина |
| `POST` | `/api/transfers/bulk-issue` | атомарно групово издаване, HTTP 201 |
| `POST` | `/api/transfers/bulk-return` | атомарно пълно или частично връщане, HTTP 200 |
| `GET` | `/api/transfer-batches` | партиди и обобщен прогрес |
| `GET` | `/api/transfer-batches/{batch_id}` | партида, индивидуални предавания и документи |
| `GET` | `/api/transfer-batches/{batch_id}/progress` | общо, върнати и все още издадени машини |
| `GET` | `/api/protocol-documents/{document_id}/download` | удостоверено изтегляне на индивидуален DOCX/PDF |
| `GET` | `/api/transfer-batches/{batch_id}/documents.zip` | всички протоколи от партидата в ZIP |

Старият `POST /api/transfers` остава съвместим и използва същия защитен service слой за единично издаване/връщане.

## Групово издаване

Полето `machine_ids` съдържа вътрешните идентификатори, получени от `/api/machines` или `/api/transfers/availability`. Следващият пример е схема; заместете означенията с реални IDs от API и не ги приемайте за бизнес данни.

```json
{
  "machine_ids": ["<machine-id-1>", "<machine-id-2>"],
  "company_unit": "<звено>",
  "vessel": "<обект>",
  "location_text": "<място на работа>",
  "location_id": "<location-id>",
  "handed_over_by": "<предал>",
  "accepted_by": "<приел>",
  "equipment": "<комплектовка>",
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
      "returned_by": "<върнал>",
      "accepted_by": "<приел>",
      "location_id": "<location-id>",
      "next_status": "Преглед"
    }
  ]
}
```

Допустимите следващи етапи са `Върната`, `Преглед`, `Почистване`, `Ремонт`, `Изчаква одобрение`, `Изчаква части` и `Тестване`. Директно `Готова` не се приема. Една заявка е атомарна, но може умишлено да съдържа само част от машините в партидата; останалите индивидуални предавания остават активни.

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

Кодове: HTTP 401 без валиден token, 403 без административна роля, 404 за липсващ ресурс, 409 за бизнес конфликт и 422 за невалидна структура/полета. Validation отговорите са нормализирани до `validation_error`, българско `message` и безопасен списък `errors`; сурови request данни и вътрешни пътища не се връщат.
