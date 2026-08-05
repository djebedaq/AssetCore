# AssetCore v8 — проверка на визуалния каталог

## Обхват

Проверен е workflow-ът:

1. избор на машина;
2. автоматично филтриране на съвместимите части;
3. избор на възел;
4. визуализиране на точния source документ и страница;
5. избор на позиция от потвърден hotspot или официалната таблица;
6. показване на Part No., описание, количество, съвместимост и източник;
7. добавяне към заявка.

## Контроли срещу измислени данни

- Основният каталог използва само `verified_only=true` записи.
- Основният визуален слой показва само `PartHotspot.is_verified=true`.
- При липса на verified hotspot позицията се маркира само в таблицата и чрез selected-position badge.
- Не се генерират автоматични hotspot координати.
- Точният документ се избира чрез `PartCatalog.source_document` ↔ `TechnicalDocument.file_path/source_key`.

## PDF preview

Endpoint:

`GET /api/technical-library/{document_id}/pages/{page_number}/preview`

Проверено:

- PNG response;
- правилна конкретна страница;
- source SHA-256 header;
- page-count header;
- ETag;
- 404 при страница извън документа;
- ограничен scale и максимален pixel budget;
- без абсолютен filesystem path в API payload.

## Изпълнени проверки

- Backend compile: успешно.
- Catalog/preview tests: 5 passed.
- Catalog + i18n/roles tests: 11 passed.
- Existing hotspot provenance/verification test: 1 passed.
- TypeScript syntax transpilation на променените frontend файлове: успешно.

## Ограничение на средата

Пълен frontend typecheck/lint/test/build не е изпълнен поради DNS грешка `EAI_AGAIN registry.npmjs.org` при опит за активиране/изтегляне на pnpm. Това е отчетено като неизпълнена проверка, а не като успешна.

## Release verifier

`scripts/verify_release.py` завърши с **21/21 успешни проверки** след промените във v8.
