# Модулно генериране на документи — серия PR #33

## Обхват и собственост

База: `df5aa50bc2f2e72d77af1ab301e1f1db11f59ffc` от `origin/main`, след
merge на asset/master-data извличането (GitHub PR #40). Номерът в серията
не е номер на автоматично създадения GitHub pull request.

Преди промяната всички функции по-долу се намират в
`backend/app/document_generation.py` (2261 реда). След промяната този файл
съдържа само explicit compatibility imports; няма генератори или DB операции.

| Нов собственик в `backend/app/documents/` | Непроменена отговорност |
| --- | --- |
| `common.py` | BG/EN/RU документен речник, media types, безопасни имена, контролирани reference SHA-256 и template-unavailable exception |
| `rendering.py` | Споделени DOCX шрифтове/таблици/отстъпи и PDF шрифтове/header/styles |
| `templates.py` | Избор на публикувана template version и preparer/signature display стойности |
| `registration.py` | Съществуваща номерация, файлови записи, canonical official/version регистрация и snapshot/signing SHA-256 |
| `transfer_documents.py` | Issue/return snapshot, template values, legacy layout builders и `make_protocol_documents` / `make_return_documents` |
| `repair_rendering.py` | Repair DOCX и тричастов PDF fallback, legacy PDF и duration/test display helpers |
| `repair_documents.py` | `make_repair_documents` и съществуващата контролирана `make_repair_correction` |
| `part_request_documents.py` | Parts snapshot, редове, legacy renderers и canonical `make_part_request_documents` |
| `daily_report_documents.py` | Съществуващият PDF дневен отчет |

Зависимостите са еднопосочни: domain builders → registration/templates/rendering
→ common. Няма imports от новия пакет обратно към compatibility модула, routes,
transfer service или repair service. `repair_documents` използва
`repair_rendering`, а не обратно.

## Съвместимост и неизменени граници

Всички 52 преместени функции, класът `ConfirmedTemplateUnavailableError` и
документните константи остават достъпни на стария import path със същите
аргументи, defaults и return types. `TemplateValidationError`, `render_docx` и
`convert_docx_to_pdf` също остават explicit re-exports. Няма wrapper функции,
динамичен module proxy или нова duplicate implementation.

`template_engine.py`, `signature_rendering.py`, `transfer_signing.py`,
`official_documents/registry.py` и `official_documents/integrity.py` не са
местени или редактирани. Routes, permission dependencies, структурирани
грешки, audit действия, transaction/locking граници и frontend са непроменени.
Builders продължават да използват `flush`, без собствен `commit`.

Няма Alembic миграция. Не са променени template/source бинарни файлове,
публикувани migration hashes, seed или провереният 19-машинен HPWJ регистър.
Единствената необходима промяна при преместване на ресурсния locator е
`parents[1]` → `parents[2]`, така че той да сочи към същата `backend/resources`.

Normal parts Generate продължава да отказва повторно генериране на същия
canonical протокол; неговите guard/lock проверки остават извън builder-а.
Repair correction продължава да връща `(documents, canonical, version)`:
съществуващият файлов suffix `-V2` принадлежи на изричната correction операция,
не на нов canonical official record. Предишните bytes, snapshots и hashes
остават непроменени.

## Output договор и регресии

`tests/fixtures/document_generation_baseline.json` е заснет **преди**
извличането от посочения base commit. Използва само съществуващия изолиран
in-memory QA generator и фиксирано тестово време; не е производствена база или
нов industrial source dataset. Не се обновява автоматично от тестовете.

`tests/test_document_generation_modules.py` проверява:

- 12 canonical протокола: issue/return/repair/parts × BG/EN/RU;
- същите номера, имена/media types, template version/source SHA, status и snapshots;
- точен SHA-256 на **всеки** DOCX ZIP member, включително XML, styles, tables,
  margins, headers, media и metadata; не само extract-нат текст;
- реалния DOCX/PDF content hash, snapshot hash и signing SHA/version формула;
- подаване на точния записан DOCX към converter-а и запазване на върнатите PDF
  bytes без повторен fallback след успешна конверсия;
- identity на old/new compatibility imports;
- неизменени предишни repair bytes/snapshots/hashes при explicit correction и
  липса на втори canonical OfficialDocument;
- caller-owned транзакции при нормално генериране и correction.

ZIP container timestamps не са канонично съдържание. PDF metadata и наличните
шрифтове/LibreOffice зависят от средата. Затова cross-platform regression
fixture-ът сравнява всички DOCX members, а не произволен raw ZIP/PDF hash;
съхраняваните в приложението hashes продължават да се изчисляват върху точните
реални файлови bytes. Production hashing не е нормализирано или отслабено.

Оригиналните integration suites остават: `test_original_protocol_layout`,
`test_bulk_transfers`, `test_transfer_workflow_v13`, `test_repair_workflow_v14`,
`test_internal_repair_protocol_v11`, `test_part_request_canonical_workflow`,
`test_official_document_registry`, `test_official_document_integrity`,
`test_integrated_transfer_signatures`, `test_issue_batch_signing`,
`test_return_batch_signing` и `test_production_hardening`.

Основни команди (от repository root; `python` е project virtualenv):

```text
python -m pytest -q tests/test_document_generation_modules.py
python -m pytest -q tests/test_original_protocol_layout.py
python -m pytest -q -m "not postgres" --durations=10
python -m pytest -q tests/postgres --durations=10
python backend/scripts/validate_migration_history.py --require-all-protected
python backend/scripts/validate_authorization_inventory.py
python scripts/verify_release.py --output release-verification
```

Layout suite трябва да се изпълни с `soffice` в PATH, за да не бъдат пропуснати
двете signed one-page проверки. PostgreSQL tests изискват отделна QA база;
production база не се използва. GitHub CI допълва full frontend, dependency
audits, catalog/translation gates, PostgreSQL backup/restore и реалния
non-root/read-only Docker runtime smoke.
