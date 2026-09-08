# QR-01 — Машинен deep link и бързи действия

## Обхват и база

База: `2effef260170d851ad558cd7648865859f34bbf4` (merged PR #71).
Branch: `assetcore-qr01-machine-entry-point`.
Квалификация: 2026-09-08. Само frontend, тестове и този отчет.
Точният commit и свежият GitHub CI са посочени в PR; този файл не твърди предварително, че CI е преминал.

## Запазен QR договор

- GET `/api/machines/{id}/qr`, permission `documents.generate`, PNG.
- Payload: `{PUBLIC_BASE_URL или request base URL}/machine/{id}`; ID е database machine ID, не инвентарният номер.
- Backend QR generation, адресът, печатът и QrCodes.tsx не са променени.
- Няма QR token, нов публичен Passport API, scan tracking, нова таблица или dependency.
- Неавтентикираният deep link показва Login, без защитен Passport GET преди успешна сесия.
- Exactly four roles; owner designation остава отделно от RBAC. QR не дава допълнителни права.

## URL / auth поведение

`useMachineEntryRoute` е тесен History API hook, не общ router.

| Случай | Резултат |
| --- | --- |
| /machine/13 | Точно DB machine ID 13 |
| /machine/13/ и /machine/0013 | Каноничен /machine/13 |
| foo, -1, abc123, 0, extra path, unsafe integer | Нормализиране към /; няма произволен Passport GET |
| Валиден, но липсващ ID | Локализиран contained 404, без вечен spinner, бутон за възстановяване |
| Authenticated direct / refresh | Същият Passport след session bootstrap |
| Login / forced password / profile completion | URL intent остава; Passport не се mount-ва преди съответния gate |
| Machines / Global Search | Същият централен Passport + /machine/{id} |
| Back / Forward | Passport и URL се синхронизират |
| Internal Close | Връщане към познатия вътрешен shell entry |
| Direct/reloaded Close | Replace към /; няма blind back към външна страница |
| Workflow / catalog handoff | Passport се затваря, URL става /, отваря се съществуващият workspace |

History metadata съдържа само transient navigation ownership. Workflow intents са в React state, не в URL, localStorage, sessionStorage или backend. Различен machine ID remount-ва keyed Passport; старият response не може да замени новата машина.

## Бързи действия

| Действие | Източник на видимост / допустимост | Съществуваща цел и stale защита |
| --- | --- | --- |
| Предай машина | active + transfers.view + backend allowed_actions.issue | Transfers → IssueModal; текуща TransferAvailability трябва да съдържа exact ID и available=true |
| Приеми машина | active + transfers.view + backend allowed_actions.return | Transfers → ReturnModal; exact ID, returnable=true и текущ active_transfer_id |
| Приеми за ремонт | active + repairs.view + backend allowed_actions.repair, без active_repair | Repairs → RepairCreateModal; repairs.create и exact active READY машина в текущия списък |
| Отвори активния ремонт | repairs.view + canonical active_repair ID | Точно текущото repair ID за същата машина, non-COMPLETED; без guessing/fallback |
| Каталог | parts.view | Съществуващ machine-specific catalog с exact ID; unsupported остава unsupported |
| Протоколи | documents.view | Съществуващ Passport tab; не започва download |
| Снимки и файлове | active + repairs.edit | Съществуващ Files tab; не отваря автоматично picker и не upload-ва |

Receiving workspace проверява отново normal permissions/актуални GET данни. Новият intent се консумира веднъж след текущото зареждане; Close и повторно посещение не го replay-ват. Нов handoff mount-ва fresh workspace, включително когато целевата страница вече е била отворена.

При stale issue/return exact target НЕ се force-select-ва и не се избира друга машина. Показва се локализирано съобщение. Stale/missing/wrong-machine/completed repair target не отваря форма за друг запис.

Няма POST/PATCH/PUT/DELETE за workflow при entry. Няма промяна на issue/return payloads, checklists, signatures, cancellation, READY/REPAIR semantics, atomicity или onComplete. Без intent старото поведение остава покрито от оригиналните тестове.

Inactive Passport е маркиран изрично; историята, разрешените протоколи и файлове не се заличават. Нови issue/return/create/file-upload shortcuts не се предлагат. Прегледът на реален active repair остава read navigation, когато е разрешен.

Observer: само съществуващият limited projection, без quick actions, tabs, timeline, QR image, протоколи, attachments или audit.

## Локализация и достъпност

9 нови ключа с изрични BG/EN/RU стойности; reuse на съществуващите catalog/protocol/files labels. Новите бутони имат текст + icon, 44 px minimum height, wrapping и focus-visible outline. Passport focus се връща към свързан opener/shell; handoff focus се поставя след mount в целевия dialog. Не остават два stacked workflow modal-а.

Няма промяна на общата modal architecture или catalog touch behavior. Files action превключва tab; не се добавя втори upload widget.

## Реален Chromium-family browser QA

Production frontend build + реален FastAPI backend, disposable SQLite база по съществуващия pytest lifecycle. Реален cookie login; няма authentication dependency override. Synthetic operation fixtures са само във временната база, извън git. Не е използвана производствената фабрична база.

| Viewport | Passport / wrapping / overflow | Workflow QA |
| --- | --- | --- |
| 1440×900 | Passport width 1120, page scrollWidth=clientWidth=1440 | Issue, Return, Repair create, active repair |
| 768×1024 | Passport width 728, page 768/768 | Issue, Return, Repair create |
| 390×844 | Passport width 335, page 375/375 (вертикален scrollbar) | Issue, Return, Repair create |
| 390×600 | Passport width 335, page 375/375; QR width 72 | Issue, Return, Repair create, inactive banner |

Всички проверени dialog-и: scrollWidth = clientWidth; няма page-level horizontal overflow. Дългото тестово име и inactive banner се пренасят. Mobile actions се достигат чрез нормално вътрешно скролване, wrap-ват и остават 44 px. Timeline tabs и съществуващият локален tab scroller са работещи.

Изпълнено:
- unauthenticated /machine/4 → Login → точно DB ID 4 / инв. №9;
- authenticated direct URL и reload → същият Passport;
- direct Close → /, без излизане от AssetCore;
- Machines → Passport → Back → Forward → Close;
- Global Search по име и сериен номер → точната машина; смяна на target;
- unknown numeric → contained localized error; malformed → /;
- Issue/Return → само точната допустима машина; празни business fields;
- Repair create → точната машина; active repair → точното repair ID;
- Catalog → DB ID 4 / инв. №9, реалният Falch каталог;
- Protocols/Files → съществуващи tabs; няма автоматично download/upload;
- History → съществуващ ASSET-03B timeline;
- stale scenario: след loaded Passport тестовата наличност е променена; Issue показва 0 избрани и disabled exact target, без mutation;
- след Close/повторно Transfers посещение няма автоматично повторно отваряне;
- real Observer login → limited Passport, 0 tabs, 0 QR images;
- BG/EN/RU actions са проверени в реалния browser.

Network evidence (само method/path/status, без bodies/credentials): workflow quick actions използват GET. Единствените мутации по време на целия QA са изричен login/logout и изрична смяна на език. Няма transfer/repair/document mutation.
Очаквани откази: unauthenticated /auth/me=401 и unknown Passport=404. Финалният browser console error/warning log е празен.
При първата настройка на disposable harness login беше 403 поради локален Origin; коригиран е само harness Origin, не production security.

Първият browser pass откри focus timing при Repair entry; тесният fix премества focus след dialog commit. Потвърдено с focused regression и повторен browser check.

Forced-password/profile gates са проверени с реалните React компоненти и изолирани HTTP fixtures, не чрез промяна на credential в браузъра.
PWA: online production shell и reload deep links работят; изпълненият committed SW тест доказва offline shell fallback и че auth/passport/timeline/QR API не се intercept/cache-ват. Няма offline workflow qualification.

**PHYSICAL QR SCAN QA = NOT EXECUTED.**
Не са квалифицирани физически етикет, камера, factory Wi-Fi или реално инсталирана PWA. Browser viewport тест не е физически scan.

## Изпълнени проверки

Командите са от repository root, освен pnpm командите (frontend). Python е съществуващият изолиран project test runtime; dependency/migration файлове не са променяни.

Baseline (untouched main):
```text
pnpm exec vitest run src/AuthSession.test.tsx src/ChangePassword.test.tsx src/features/passport src/features/machines/Machines.test.tsx src/RoleNavigation.test.tsx src/shell/ScreenContracts.test.tsx src/shell/ServiceWorker.test.ts src/shell/LazyNavigation.test.tsx src/BulkTransfers.test.tsx src/features/transfers/__tests__ src/RepairWorkflow.test.tsx src/features/repairs/workflow.test.ts
```
19 files / 248 passed.

Focused additions: MachineEntryRoute 23, MachineEntryActions 25, QrCodes 2; 3 съществуващи ServiceWorker tests с допълнителни protected-path assertions. Съществуващите passport/transfer/repair/auth тестове са запазени.

```text
pnpm exec vitest run src/features/passport/MachineEntryRoute.test.tsx src/features/passport/MachineEntryActions.test.tsx src/shell/ServiceWorker.test.ts
pnpm exec vitest run src/features/qr/QrCodes.test.tsx
pnpm exec vitest run src/features/passport/MachineEntryActions.test.tsx
pnpm install --frozen-lockfile
pnpm typecheck
pnpm lint
pnpm test
pnpm build
python scripts/audit_dependencies.py frontend --output .tmp/frontend-audit.json
python -m pytest -q tests/test_asset_master_data_contracts.py tests/test_machine_passport_v2.py
python -m pytest -q tests/test_passport_availability_metadata.py
python -m compileall -q backend/app backend/alembic backend/scripts scripts tests
python -m ruff check backend/app backend/alembic backend/scripts scripts tests
python backend/scripts/validate_migration_history.py --require-all-protected
python backend/scripts/validate_authorization_inventory.py
PYTHONPATH=backend python backend/scripts/catalog_v2_validation.py
PYTHONPATH=backend python backend/scripts/build_catalog_translations.py --check
python scripts/verify_release.py --output .tmp/release-verification
```

- Focused route/action/SW development run: 47 passed (преди добавянето на още 4 role assertions); final action rerun: 25 passed; QR: 2 passed.
- pnpm full suite: **43 files / 474 passed**, включително след browser focus correction.
- Typecheck / lint / production build: success след final correction.
- Frozen install: success, lockfile unchanged. Dependency audit: 350 dependencies, valid=true, 0 blocking/0 informational.
- Production initial JS: 473.17 kB (131.80 kB gzip); няма chunk-size threshold change.
- Backend QR/master-data/passport: 19 passed; availability metadata: 8 passed (**27 total**).
- compileall / Ruff: success.
- Migration: valid=true, history_valid=true, protected_count=21, missing=[], mismatched=[], new_unprotected_migrations=[].
- Authorization: valid=true, 167 routes / 80 mutating, errors=[].
- Catalog/translations/release verifier: success.
- Existing test-runtime deprecation warnings (Starlette/httpx, anyio, reportlab, pypdf) и съществуващи SQLite Alembic warnings са отчетени, не потискани.
- Development test fixture corrections: response clone on remount, missing typed field, actual accessible labels и async image/select readiness. Final tests pass; не е променен production QR/catalog behavior заради fixture assertions.
- Full frontend е повторен след действително открития browser focus fix; не са повтаряни full backend suites локално.
- Full backend / PostgreSQL / Docker: свежите required GitHub jobs на exact PR head са release qualification; локални PostgreSQL/Docker не са заявени като изпълнени.

## Данни и изрични граници

Release/catalog validators: 19 verified HPWJ, 611 records, 581 positions, 818 hotspots, 237 duplicate callouts, 0 unresolved, 2 not-drawn, 7 kits / 84 components, BG/EN 611/611, 9/9 source fingerprints. Няма промяна на seed, catalog/source/template/document/signature files. CombiJet и №19 не получават ново mapping.

NO DATABASE SCHEMA CHANGE. NO MIGRATION.
QR PRINTED-LABEL CONTRACT UNCHANGED. NO QR TOKEN ADDED.
NO PUBLIC UNAUTHENTICATED MACHINE DATA.
ASSET-03A BACKEND UNCHANGED.
ASSET-03B UI UNCHANGED EXCEPT LEGITIMATE PASSPORT ENTRY/ACTION WIRING.
PARTS-DOC-01 NOT IMPLEMENTED.
PR NOT MERGED.
