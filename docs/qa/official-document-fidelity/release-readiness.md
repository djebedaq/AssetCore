# Release readiness

Правило за финалното становище: **READY** само когато всичките пет CI jobs за един и същ окончателен PR head са успешни; при всеки отказ или неприключила проверка — **NOT READY**. Актуалният head и финалното становище се записват в PR #116 и финалния отчет, за да не се представят резултати от по-стар commit като проверки на новия.

## Реализирано

Контролиран exact converter за четирите бизнес типа и петте реални разновидности на BG/EN/RU. Native OOXML, editable projection, един manifest за machine/free KK; server-side variant validation; неизменни source bytes; fail-closed approval/archive; read-only selection diagnostics; actual PDF previews и source download; оригинални authorized images; преведени Repair table labels и controls. Не се добавя migration или нов бизнес counter.

Нови API: `GET /api/studio/configuration/{document_type}/{language}` и `GET /api/studio/drafts/{draft_id}/native-images/{block_id}`. Разширени са legacy draft copy, draft preview input с request_variant и version preview query request_variant; publish валидира двата KK варианта. Всички ползват съществуващите permission boundaries. Поддържат се schema 1–3; новият native договор е schema 4 / adapter 1.

## Изпълнени локални проверки

| Команда | Реален резултат |
|---|---|
| `python -m ruff check backend/app backend/alembic backend/scripts scripts tests` | PASS; след новите файлове се изпълнява отново |
| `python -m pytest -q tests/test_official_document_fidelity.py --tb=short` в изолиран Linux converter image | 45 passed, 3 warnings, 188.49 s; включва реално publish/activate/approve/archive/restore и каталожни приложения |
| `PYTHONPATH=backend:tests DATABASE_URL=sqlite:///:memory: python tests/generate_official_fidelity_evidence.py` | 45 случая, 75 page pairs, DOCX text/PDF text/page counts/raster equal |
| `PYTHONPATH=backend python tests/verify_official_fidelity_evidence.py` | PASS: 45 actual pairs, 75 page pairs, 757 protected paths; проверява самите файлове, не само запазения JSON |
| `python scripts/audit_dependencies.py python --output docs/qa/official-document-fidelity/security/python-audit.json` в изолиран audit image | PASS: 80 dependencies; no blocking findings; informational pip findings видими |
| `pnpm typecheck`, `pnpm lint`, `pnpm build` (съответните package script commands чрез наличния Node runtime) | PASS; build запазва съществуващото предупреждение за голям chunk |
| `vitest run src/features/documentStudio src/features/catalogBuilder/SourceWorkspace.test.tsx` | 6 files, 31 tests passed |
| `python tests/browser/run_official_document_fidelity_qa.py` | успешен run: 14 checks, 52 screenshots; повторението след компактния page-settings panel и image-load assertions също е успешно |

Предходен пълен локален frontend run е 702 passed; по-късен паралелен run е 701 passed / 1 timeout в SourceWorkspace (5 s). Фокусираното повторение преминава 31/31 без увеличаване на timeout или отслабване на assertions. CI frontend също е успешен за междинните code heads. Извикване на eslint върху целия frontend root беше невалиден обхват спрямо package script; действителната проверка е `eslint src --max-warnings 0`.

Предходният пълен локален backend run беше прекъснат след 690 passed / 2 failures / 1 skipped. Двата отказа бяха за предишния machine-only starter при FREE_FORM и за вече поддържаната schema 4; поправени са с dual starter и unknown-schema regression към 5. Това не се отчита като успешен full suite. Авторитетен пълен резултат е backend CI за окончателния head.

Първите browser повторения откриха липсващ CONDITION_LABEL, variant control accessibility и стар schema-2 QA сценарий, който неправилно изискваше FREE_FORM успех с machine-only source. Новият сценарий проверява конкретния 409 отказ и отделно реално машинно издаване със синтетични данни; не премахва archive proof.

Допълнителни целеви проверки: `pytest -q tests/test_official_document_fidelity.py -k "ambiguous or effective_window" --tb=short` — 3 passed; `-k image_replacement` — 1 passed. Допълнителният native-transfer diagnostics regression е 1 passed; първоизточникът е отделен от Studio version, без KK programmatic номера за transfer. `validate_migration_history.py --require-all-protected` — PASS, 39 migrations. `validate_authorization_inventory.py` — PASS, 330 routes / 168 mutating, без errors. Старият schema-2 Chromium сценарий — 8 checks / 22 screenshots, PASS.

## Preservation и ограничения

`preservation.json`: 757 действителни baseline paths с Git blob и SHA-256, без променен защитен path. Включени са всички стари migrations, resources, scripts, seed/source registers и document/image binaries. `visual-review.json`: 51 различни raster hashes, прегледани при оригинална резолюция, покриващи всички 75 page pairs.

Реалните частни DOCX са hash-проверени, структурно и визуално прегледани, но не са публикувани. Контролирани източници, 19-machine seed, registers, исторически QA binaries и production scripts не са променени. Не са използвани Production база или конфигурация. Няма merge, deployment или Production template activation.

Native структурни операции извън поддържания договор се отказват. Реалният KK не притежава графични signature cells; бизнес одобрението е запазено, добавяне на графичен signer се отказва преди session mutation. Repair v6 не съдържа отделна event-history таблица; поддържаните v6 данни се запазват. Подробности: risk-register.md и self-review.md.

## Финални блокиращи gates

Петте jobs — frontend, backend, postgres, browser, docker — трябва да са success за един и същ окончателен PR head. До приключването им release становището е NOT READY. Локалният успех не замества PostgreSQL concurrency, backup/restore и цялата CI регресия. Публикуване или активация в Production не е част от тази задача.
