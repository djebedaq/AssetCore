# COMMERCIAL DOCS 01C — QA доказателства

Работен отчет; финалните CI и Chromium резултати предстоят. Не е разрешение за merge или deployment.

## Потвърдено локално

- `pnpm typecheck`, `pnpm lint`, `pnpm test`, `pnpm build`: успешни; 702 frontend теста.
- `python -m pytest tests/test_studio_proposals.py tests/test_document_studio.py -q`: 76 passed.
- `python -m pytest tests/test_studio_proposals_migration.py -q`: 1 passed, SQLite additive upgrade и отказ от загуба на история при downgrade.
- Изолиран Linux/Docker с реален конвертор: `tests/test_studio_proposals_rendering.py` и `tests/test_document_studio_fidelity_workflows.py`: 3 passed; допълнителното запазване на архивите след proposal publication е повторено отделно, 1 passed.
- Изолиран PostgreSQL 16: `tests/postgres/test_studio_publication_postgres.py` и `tests/postgres/test_studio_proposals_postgres.py`: 4 passed, включително истински едновременни решения/коментари и activation/restore.
- Ruff: успешен за backend/app, миграции, скриптове и тестове.
- Migration history: 39 protected, старите 38 без промяна. Authorization inventory: 328 routes, 168 mutating, 294 permission-protected, без грешки (включва 3 static routes).
- Frontend dependency audit: успешен. Python audit се повтаря след фиксиране на поправените Pillow/certifi/pypdf версии.

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

## Оставащи проверки преди завършване

Финален успешен Chromium сценарий с приложени screenshots, повторна документна регресия с фиксираните зависимости, пълните пет CI jobs на точния финален commit и финален преглед на diff/preservation.
