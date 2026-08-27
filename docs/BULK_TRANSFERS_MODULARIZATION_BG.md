# PR #36 — модулен frontend за групови предавания

## Обхват и собственост

База: `36ff0ca306e006ac60c4c7a5d748673abfa0f2c9` — merge на frontend shell задачата (логически PR #35, GitHub PR #44). Работен branch: `assetcore-bulk-transfers-frontend-modularization`.

Изнасяне на съществуващия код, без преднамерена промяна на workflow, UX или API. Няма backend application, schema, migration, permission, i18n, CSS, signature, template, seed или source промени. Единствената Python промяна е актуализираният static UI wiring regression test.

Преди: `frontend/src/BulkTransfers.tsx` съдържа 792 реда / 46 310 UTF-8 bytes (LF). След: същият public entry е 9 реда, а feature coordinator-ът е 114 реда — 85,6% по-малък от първоначалния монолит. Логиката е преместена, не изтрита.

Всички нови production модули са под `frontend/src/features/transfers/`:

| Предишна отговорност в монолита | Нов собственик | Редове |
| --- | --- | ---: |
| Availability, permissions, зареждане/опресняване, избор на модал | `BulkTransfers.tsx` | 114 |
| Избор, issue draft, потвърждение, подписни стъпки, резултат | `IssueFlow.tsx` | 162 |
| Индивидуални return drafts, READY/REPAIR, частичен резултат | `ReturnFlow.tsx` | 193 |
| Анулиране на pending партида с причина | `CancelBatchModal.tsx` | 88 |
| Batch progress/details и реални document actions | `BatchHistory.tsx` | 33 |
| Confirmation summary и issue result | `TransferSummary.tsx` | 51 |
| Availability selection rows | `IssueSelectionList.tsx` | 37 |
| Condition/checklist editor | `TransferChecklist.tsx` | 9 |
| Съществуващият transfer modal shell | `TransferModalShell.tsx` | 20 |
| Structured/localized conflict presentation | `TransferConflictNotice.tsx` | 55 |
| Същият embedded `SignaturePage` markup | `SignatureStep.tsx` | 13 |
| Draft типове, константи и чиста payload сериализация | `transferState.ts` | 83 |
| Тънка граница към съществуващия `api.ts` | `transferApi.ts` | 17 |

`Transfers.tsx` импортира feature coordinator-а директно. Старият import path запазва `default` и всичките девет named exports като същите функции, не wrappers: `BatchDetailsPanel`, `BatchProgressCard`, `CancelBatchModal`, `ConfirmationSummary`, `IssueResult`, `ConflictNotice`, `IssueModal`, `IssueSelectionList`, `ReturnModal`. Това се проверява с `Compatibility.test.ts`.

## Непроменен договор

| Действие | Същият HTTP договор чрез `api.ts` |
| --- | --- |
| Наличност | `GET /api/transfers/availability` |
| Активни местоположения | `GET /api/locations` |
| Партиди / детайли | `GET /api/transfer-batches`, `GET /api/transfer-batches/{id}` |
| Издаване | `POST /api/transfers/bulk-issue` |
| Връщане | `POST /api/transfers/bulk-return` |
| Анулиране | `POST /api/transfer-batches/{id}/cancel` с `{reason}` |

Подписването продължава да се извършва само от непроменения `SignaturePage.tsx`: summary GET, signature POST, confirm/reject POST. Download действията използват backend-returned endpoints и същия `downloadApiFile`; няма нов URL или client-side генериране на документи.

- Изборът се управлява от server `available`/`returnable`, не от локално тълкуване на `status`.
- Issue payload запазва реда на `Set`, текущото trim поведение, `document_language: 'bg'`, checklist и recipient полетата. Return payload пази `Object.values(drafts)` и индивидуалните стойности без ново нормализиране.
- Празна checklist дължина остава `null`, непразна — `Number(value)`; празната бележка остава `null`. Съществуващите 10 item codes и шест condition codes са непроменени.
- Server task order/count и legacy per-transfer task fallback остават същите. Няма нов `key`/remount на подписния компонент. `onComplete` се извиква след последния confirm или при нулев брой server tasks, не след първи подпис.
- Отказът от подпис не финализира операцията. Анулирането остава отделен backend POST с причина; pending documents/ZIP остават недостъпни.
- Частичното връщане изпраща само избраните активни transfer IDs. READY/REPAIR, липси, повреди, замърсяване и notes остават индивидуални. Backend запазва authority за финалния status/location, ремонта, atomicity, idempotency и race protection.
- Error codes/conflicts остават структурирани и локализирани. Селекцията и draft полетата не се губят при conflict.

Локално mechanical сравнение с базовия commit установи еквивалентни тела на всичките 15 оригинални функции след inlining само на новите API/payload/SignatureStep callsites. Сравнени са и оригиналните payload literals, checklist serializer, draft constants/types и signature markup. Това допълва, а не замества integration тестовете.

## Регресионни тестове

Добавени са 23 frontend теста (112 общо, преди 89):

- `TransferFlows.test.tsx` — 11: keyboard/search selection, server availability, checklist редакция, foreign-name exception, exact JSON payload, double-click pending guard, issue/return conflict retention, READY/REPAIR drafts, deselection, partial progress/document actions, cancellation failures/refresh и permissions.
- `TransferSignatures.test.tsx` — 8: реалният embedded `SignaturePage` с mocked HTTP/canvas; issue/return, top-level/legacy task lists, 2/3 configured tasks, exact request order, no premature completion, rejection/cancellation и unavailable session. Pointer regression проверява и body scroll lock/unlock при touch.
- `transferState.test.ts` — 3: exact serialization/defaults и независими checklist drafts.
- `Compatibility.test.ts` — 1: целият стар public import surface.

19-те component/signature characterization tests бяха изпълнени срещу оригиналния монолит преди extraction: заедно със старите `BulkTransfers.test.tsx` и `ProductionHardening.test.tsx` — 34/34. Новите тестове използват test-only fixtures; не записват бизнес данни.

## Проверки

Командите са от repository root, освен `pnpm` командите (директория `frontend`). `python` по-долу е `backend/.venv/Scripts/python.exe`; local bundled Node/pnpm са добавени само към PATH на процеса. Няма промяна на dependency manifests/lockfile.

| Команда | Резултат |
| --- | --- |
| `python -m pip install -r backend/requirements.txt -r backend/requirements-ci.txt --disable-pip-version-check` | Успех |
| `pnpm install --frozen-lockfile` | Успех |
| `pnpm typecheck` | Успех |
| `pnpm lint` | Успех |
| `pnpm test` | 112 passed, 25 files |
| `pnpm build` | Успех, 1642 modules |
| `python -m pip check` | Успех |
| `python -m compileall -q backend/app backend/alembic backend/scripts scripts tests` | Успех |
| `python -m ruff check backend/app backend/alembic backend/scripts scripts tests` | Успех |
| `python -m pytest -q -m 'not postgres' --durations=10 --tb=short -o cache_dir=.tmp/pr36-transfer-qa/pytest-cache --basetemp=.tmp/pr36-transfer-qa/backend-tests --junitxml=.tmp/pr36-transfer-qa/backend-test-results.xml` | 302 passed, 2 skipped (LibreOffice извън PATH), 5 PostgreSQL deselected; 984,93 s |
| `python backend/scripts/validate_migration_history.py --require-all-protected` | valid; protected=21, missing=[], mismatched=[], new=[] |
| `python backend/scripts/validate_authorization_inventory.py` | valid; 167 routes, 80 mutating, 0 errors |
| `PYTHONPATH=backend python backend/scripts/catalog_v2_validation.py` | Успех; 611 source rows / 9 sources |
| `PYTHONPATH=backend python backend/scripts/build_catalog_translations.py --check` | Успех; 611 canonical identities |
| `python scripts/audit_dependencies.py python --output .tmp/pr36-transfer-qa/python-audit.json` | valid; 87 dependencies, 0 findings, 0 exceptions |
| `python scripts/audit_dependencies.py frontend --output .tmp/pr36-transfer-qa/frontend-audit.json` | valid; 350 dependencies, 0 findings, 0 exceptions |
| `python scripts/verify_release.py --output .tmp/pr36-transfer-qa/release-rerun` | Всички release checks PASS, включително inventory/serials, templates и DOCX/PDF/hash QA |
| `python scripts/verify_release.py --output .tmp/pr36-transfer-qa/release-staged` | Повторно PASS с всички нови файлове в Git index |

Първият local release run спря на `git ls-files` с Git ownership exit 128. Повторението използва процесни `GIT_CONFIG_COUNT=1`, `GIT_CONFIG_KEY_0=safe.directory` и конкретния repository path за `GIT_CONFIG_VALUE_0`; без промяна на validator или глобален Git config.

Пълният backend run включва 45 issue/return/signature/checklist/cancellation регресии: `test_bulk_transfers.py` (24), `test_integrated_transfer_signatures.py` (4), `test_issue_batch_signing.py` (1), `test_return_batch_signing.py` (3), `test_transfer_workflow_v13.py` (5), `test_transfer_checklist_schema.py` (2), `test_transfer_cancellation_schema.py` (3), `test_safe_cancellation_ui_contract.py` (3). Не са заменени с superficial assertions. Има съществуващи dependency deprecation/SQLite migration warnings; няма failed backend тест.

Production bundle: initial JS **444 483 bytes** преди и след, 23 JS chunks; transfer chunk **34,49 → 34,47 kB** според Vite (след: 34 470 bytes). Няма промяна на lazy boundary или bundle warning threshold. CSS fingerprint остава `index-Do_-Xp-I.css`. Измерване: `node frontend/scripts/measure-bundle.mjs frontend/dist`.

PostgreSQL: `python .tmp/pr36-transfer-qa/run_postgres_qa.py` стартира изолиран local cluster и изпълни реалните `python -m pytest -q tests/postgres --durations=10 --tb=short --junitxml=.tmp/pr36-transfer-qa/postgres-test-results.xml -o cache_dir=.tmp/pr36-transfer-qa/pytest-cache --basetemp=.tmp/pr36-transfer-qa/postgres-tests` и `python scripts/postgres_smoke_test.py`: **5/5 passed**, migration/downgrade/upgrade и encrypted backup/restore PASS. Тестовите credentials не се публикуват; cluster-ът е спрян след проверката.

LibreOffice: с portable `program` директорията в PATH, `python -m pytest -q tests/test_original_protocol_layout.py -o cache_dir=.tmp/pr36-transfer-qa/pytest-cache --basetemp=.tmp/pr36-transfer-qa/layout-tests-rerun --junitxml=.tmp/pr36-transfer-qa/layout-test-results-rerun.xml` — **8 passed**, включително issue/return подписи на оригиналната A4 страница. Първият run (`--basetemp=.tmp/pr36-transfer-qa/layout-tests --junitxml=.tmp/pr36-transfer-qa/layout-test-results.xml`, без cache override) завърши 7 passed / 1 skipped: първото draft PDF преобразуване върна `None`; повторението с вече стартирания portable runtime изпълни и осемте теста без skip.

Docker: `docker compose config --quiet` и `docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet` преминаха с изолирани QA настройки. `docker build --tag assetcore:pr36-transfer-qa .` не стартира build: липсва local `dockerDesktopLinuxEngine` pipe. Local runtime smoke не е изпълнен; GitHub Docker job остава задължителен.

## Browser QA и ограничения

Реален production frontend + локален FastAPI, изолирана временна SQLite база. Нито една QA операция не е върху production/customer база. Използвани са отделен QA акаунт и синтетични тестови подписи, не подписи на реални лица.

Проверени viewport-и: desktop **1440×900**, mobile **390×844** и short mobile **390×600**. Прегледани са реални screenshots на mobile signature canvas/actions и return confirmation; няма хоризонтално излизане на тези екрани. Това е desktop browser с viewport emulation, не тест върху физически телефон.

- Реален login/reload/session bootstrap; празно batch/history състояние.
- Избор на две машини през search, checklist condition/length/note редакция и confirmation преди POST.
- Реално издаване с два последователни синтетични подписа, review/confirm за всеки, собствен протокол за всяка машина, DOCX/PDF actions и ZIP action.
- Частично връщане само на №4 към REPAIR с checklist и бележка: след двата return подписа workspace показва 1 върната / 1 все още издадена; №5 остава издадена.
- Pending READY връщане на №5: отказ от подпис, без completed document actions, след това изрично анулиране с причина. Първоначалното издаване на №5 остава активно.
- След reload и двете машини са недостъпни за ново издаване с точните server причини: №4 е в ремонт в Цех, №5 има активно издаване на Док 2. Изолираната QA услуга е спряна, временният login файл е премахнат и viewport override-ът е възстановен.

ZIP бутонът е натиснат в браузъра; записването на файл чрез системния download dialog не е независимо потвърдено. Binary ZIP/doc/hash correctness се проверява от backend integration тестовете и release verifier. HTTP conflict rendering, pending double-submit и draft retention са проверени с component tests, не чрез изкуствено променяне на реалния browser API.

Наблюдавани **съществуващи baseline ограничения**, оставени непроменени в zero-workflow-change PR:

1. След последния return подпис result modal-ът обновява `returned`, но не обновява `result.batches`; неговата вътрешна progress карта временно показва pre-sign snapshot. Опресненият основен batch списък показва правилния частичен напредък. Същият `finishSignature` е в базовия commit.
2. Batch badge за анулирана операция показва техническото `CANCELLED`: непромененият `batchStatusKeys` няма mapping за този код. Това не променя server cancellation състоянието.

Тези два UI дефекта изискват отделна behavior-fix задача; не са прикрити като част от extraction. Няма промяна на 19-machine inventory, serials, source register, catalog или контролирани документи. GitHub CI статусът се отчита за действително публикувания head; PR остава отворен за review, без merge.
