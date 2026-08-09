# Repair workflow и protocol v5 — техническа валидация

## Намерени причини и корекции

- Текущият main съчетаваше запис на формата и status transition без ясен primary UX; status pills изглеждаха като действия, а generic frontend fallback скриваше конкретната server причина. Записът и продължаването вече са отделни действия, а backend валидира полетата на целевия етап и връща структурирано BG съобщение.
- Единичното participant API записване не беше възпроизводимо като дефект върху чист current main. Реалният непокрит риск беше повторен/double submit: UI нямаше pending guard, а DB нямаше repair-scoped idempotency constraint. Добавени са и двете защити, без промяна на исторически snapshots.
- Completion логиката съществуваше по два маршрута и не гарантираше навсякъде едновременно location `Цех`, approver и еднаква document transaction. Общите helper-и вече обслужват и основния, и compatibility маршрута.
- Timeline можеше да показва непознат технически code. Централният i18n mapping покрива repair/participant/part/attachment/document/ready events и използва безопасен локализиран fallback вместо raw code.

## Миграция

`20260809_0017_repair_workflow_protocol.py` добавя nullable `required_parts_text`, `diagnosis_minutes`, `repair_minutes`, `testing_minutes`, три non-negative check constraints и nullable participant `identity_key` с уникален `(repair_id, identity_key)` индекс. Legacy participant rows не се backfill-ват, така че миграцията не създава конфликт и не променя историята. Upgrade/downgrade използват Alembic batch операции за SQLite и стандартни PostgreSQL-compatible constraints/indexes.

## Използване на референтния документ

Външният `Топтоптоп.docx` е прочетен структурно и рендериран само за съдържателна/визуална референция. Неговият SHA-256 е `1D92C2FC6EE6EC4BC367F83F1140DA86BC100963BE58C7F4542FB59EEEE69201`. Той не е модифициран и не е добавен в Git. Примерните хора, машина, части, дати и текстове не са копирани като AssetCore бизнес данни.

Repair v5 използва съдържателното разделение на приемане и завършен ремонт, но собствен approved AssetCore transfer v3 header. BG executable template SHA-256 е `E324BB1F74CF1E60F88774D550EF1AE6EB46EF8FE7A49C2E9A263E2F63D061E0`.

## Document QA

`backend/scripts/document_qa.py` генерира issue, return, repair и part-request DOCX/PDF в изолирана QA среда. Repair DOCX е конвертиран с LibreOffice и PDF е рендериран с Poppler. Проверени са всички 3 generated страници и 2 reference страници: няма clipping, overlap, повредена кирилица или случайна празна страница. Repair има точно 3 страници; issue/return остават по 1 страница. Embedded header media съвпадат с approved transfer v3, а source document hashes остават непроменени.

Тестовите стойности са само в изолирани временни бази и QA файлове. Verified catalog тестът използва record от `backend/resources/catalog/verified_parts_v1.json`; не е добавена нова машина, part number или production business record.
