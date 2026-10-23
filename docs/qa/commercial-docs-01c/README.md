# COMMERCIAL DOCS 01C — QA доказателства

Реални UI и документни доказателства от изолирани синтетични QA бази. Авторитетните резултати за точния финален commit са в [PR #115 → Checks](https://github.com/djebedaq/AssetCore/pull/115/checks). Този отчет не разрешава merge или deployment.

## Потвърдено локално

- `pnpm typecheck`, `pnpm lint`, `pnpm test`, `pnpm build`: успешни; 702 frontend теста.
- `python -m pytest tests/test_studio_proposals.py tests/test_document_studio.py -q`: 76 passed.
- `python -m pytest tests/test_studio_proposals_migration.py -q`: 1 passed, SQLite additive upgrade и отказ от загуба на история при downgrade.
- Изолиран Linux/Docker с фиксираните зависимости: `python -m pytest tests/test_studio_proposals.py tests/test_studio_proposals_rendering.py -q --tb=short --maxfail=1`: 31 passed. Проверява отделното публикуване, exact draft/version trace, еднакъв DOCX hash при еднакви preview данни и private/no-store отговор. Каноничната четирипроцесна регресия е повторена и доказателствата ѝ са приложени по-долу.
- Изолиран PostgreSQL 16: `tests/postgres/test_studio_publication_postgres.py` и `tests/postgres/test_studio_proposals_postgres.py`: 5 passed, включително истински едновременни решения/коментари, опит за guessed future revision и activation/restore.
- Ruff: успешен за backend/app, миграции, скриптове и тестове.
- Migration history: 39 protected, старите 38 без промяна. Authorization inventory: 328 routes, 168 mutating, 294 permission-protected, без грешки (включва 3 static routes).
- [Frontend audit](security/frontend-audit.json): 342 dependencies, 0 blocking/informational/exception. [Python audit](security/python-audit.json): 81 dependencies, 0 blocking/informational/exception след фиксиране на Pillow 13.0.0, certifi 2026.10.19 и pypdf 6.21.1. `pip check`: успешен.

## Реални официални документи

| Процес | DOCX / PDF | PNG страници | Проверено |
|---|---|---|---|
| Предаване | [DOCX](regressions/transfer-issue/official-synthetic.docx), [PDF](regressions/transfer-issue/official-synthetic.pdf) | [1](regressions/transfer-issue/official-synthetic-page-1.png) | 10 канонични issue позиции, исторически условия, две графични подписни клетки |
| Връщане | [DOCX](regressions/transfer-return/official-synthetic.docx), [PDF](regressions/transfer-return/official-synthetic.pdf) | [1](regressions/transfer-return/official-synthetic-page-1.png) | 10 return позиции, различен записан snapshot, правилни участници |
| Ремонт | [DOCX](regressions/repair-protocol/official-synthetic.docx), [PDF](regressions/repair-protocol/official-synthetic.pdf) | [1](regressions/repair-protocol/official-synthetic-page-1.png), [2](regressions/repair-protocol/official-synthetic-page-2.png) | Repair v6 секции, записани диагностика/ремонт/тест, история и authorized finalization |
| KK | [DOCX](regressions/parts-request/official-synthetic.docx), [PDF](regressions/parts-request/official-synthetic.pdf) | [1](regressions/parts-request/official-synthetic-page-1.png), [2](regressions/parts-request/official-synthetic-page-2.png), [3](regressions/parts-request/official-synthetic-page-3.png) | 4 колони, frozen approval identity/template bytes, две подписи и контролирани приложения в правилен ред |

Всичките седем PNG страници са рендерирани от действителните PDF-и и са визуално прегледани. Няма отпечатан текстов placeholder за липсващо лого, припокрити подписи или отрязани основни таблици. Шапката е неутрална и умишлено с празни позиции за лога. Каталожните страници запазват собствените си одобрени изображения и обозначения. Синтетичните подписи са тестово изображение/щрих, не реални подписи.

Това е повторна интеграционна регресия на поддържаната структура, не ново твърдение за pixel-perfect еквивалентност. Подробните оригинални comparison матрици/страници от [01B final fidelity](../commercial-docs-01b/final-fidelity/README.md) остават непроменени.

## Неизменност

[official-workflow-proof.json](regressions/official-workflow-proof.json) съдържа hash/status/checklist/signature проверки за четирите официални процеса. [proposal-archive-preservation.json](regressions/proposal-archive-preservation.json) сравнява всички редове и байтове на machines, official document versions, generated/protocol documents, approval snapshots, KK counter и activation history преди/след submit → accept → exact draft → real preview → separate publication. Всичките седем SHA-256 стойности съвпадат.

[preservation.json](preservation.json) сравнява с проверения base `48600622f6bc69d9783ad0e119cf379699f71e31`: 256 защитени материала, 602 съществуващи binary документа/QA файла и старите 38 миграции са непроменени. За binary файловете са сравнени суровите работни байтове с точния Git blob. Seed/source register и deployment скриптовете са запазени. Синтетичните бизнес записи съществуват само в изолирани QA бази; база данни не е добавена в Git.

## Chromium и компактност

`python tests/browser/run_document_studio_proposals_qa.py`: passed, 5 групи проверки, 34 реални screenshots, 0 browser runtime errors. [Галерията](browser/README.md) съдържа всички сценарии и BG/EN/RU при 390/768/1440 px. Администраторът в сценария е отделен акаунт без owner статус (проверен чрез /auth/me). Приемане, отказ и коментар са изпълнени с touch на 390 px; кирилско търсене, разрешено изображение, dialog focus, labels и липса на document-level horizontal overflow са проверени с assertions.

[Компактен DOCX](browser/compact-missing-logo.docx), [actual PDF](browser/compact-missing-logo.pdf), [PNG страница](browser/compact-missing-logo-page-1.png): текущата чернова е променена чрез UI preset, записана чрез CAS и публикувана отделно. Не е активирана. [browser-proof.json](browser/browser-proof.json) пази exact target/draft/published IDs и потвърдени source hashes. [artifact-manifest.json](artifact-manifest.json) изброява SHA-256 на 5 DOCX/PDF двойки, 8 действителни PDF страници и 34 UI screenshots.

## Финални CI и ограничения

Петте задължителни jobs са Frontend, Backend, PostgreSQL, Browser и Docker. Проверяват се върху финалния PR commit; резултат от по-стар commit не е достатъчен. Точният head SHA, run/job links и окончателните числа са в описанието на [PR #115](https://github.com/djebedaq/AssetCore/pull/115). CI включва пълните съществуващи suites, security audit, migration/authorization inventory, всички A/B browser сценарии и новия C сценарий. Няма изключени или отслабени проверки; актуализирани са очакваните route counts и Alembic head за добавените API/0039.

DOCX import остава reference-only. Стар обикновен текстов placeholder във frozen публикувана версия не се пренаписва; заменя се с logo block в нова чернова/версия. Няма автоматични emails, activation или deployment. Проверките за достъпност са конкретни keyboard/label/responsive assertions, не пълна WCAG сертификация.
