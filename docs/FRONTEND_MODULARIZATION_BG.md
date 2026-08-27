# Frontend shell и page-level модули — задача PR #35

## Обхват и непроменени договори

База: `b10c8ca7d3c0ef0ebf41f630a3c2dee9b6c74657` (`main`, след governance PR и HTTP 423 корекцията).
Branch: `assetcore-frontend-shell-modularization`. PR не се merge-ва автоматично.

Няма backend, schema, API, permission, inventory, source, template или document промяна.
Не са променени `api.ts`, `permissions.ts`, `i18n.tsx`, `locale.ts`, `types.ts`,
`styles.css`, `useMobileNavigationLock.ts`, signing/transfer логиката и service worker.
BG/EN/RU ключовете, sidebar редът и permission филтърът са същите.
`/machine/:id`, `/sign/:token`, session bootstrap/401/logout, parts badge и
паспорт → каталог запазват съществуващите договори.

## Собственост преди / след

| Преди | След |
| --- | --- |
| App: Login / LanguageSwitcher | `features/auth/Login.tsx` / `shell/LanguageSwitcher.tsx` |
| App: Dashboard | `features/dashboard/Dashboard.tsx` |
| App: Machines / MachineModal | `features/machines/` |
| App: Transfers / Reports / Audit / QR | `features/transfers/`, `reports/`, `audit/`, `qr/` |
| App: SettingsPage | `features/administration/SettingsPage.tsx` |
| IndustrialPlatform: GlobalSearchBox | `features/search/GlobalSearchBox.tsx` (eager shell control) |
| IndustrialPlatform: MachinePassportModal | `features/passport/`, общ lazy modal за search, deep link и машинния списък |
| IndustrialPlatform: TechnicalLibrary / upload modal | `features/technicalLibrary/TechnicalLibrary.tsx` |
| IndustrialPlatform: AdministrationPanel | `features/administration/AdministrationPanel.tsx` |
| Root UserAdministration / GovernancePanel | `features/administration/` |
| Root OfficialDocuments | `features/officialDocuments/OfficialDocuments.tsx` |
| App: legacy PartCatalog / Documents | `features/catalog/LegacyPartCatalog.tsx` / `features/technicalLibrary/LegacyDocuments.tsx` |
| Съществуващи catalog / repairs / partRequests features | Същите файлове и поведение, вече page-level lazy imports |

`App.tsx`: **897 → 219 реда**, 42 437 → 10 620 bytes (локални файлове).
`IndustrialPlatform.tsx`: **347 → 9 реда**, 52 691 → 726 bytes.
AST проверка срещу базата сравни телата на **24 функции в 19 изнесени файла**
след LF normalization: всички са идентични. Това допълва, не заменя, integration тестовете.
Отделно сравнение на `App` след премахване само на добавените boundary wrappers
потвърди идентични hooks, navigation, permission филтър и callbacks.

### Временна съвместимост

`IndustrialPlatform.tsx` запазва седемте named exports за съществуващи callers/tests;
нов production код трябва да импортира конкретния feature, не този barrel.
Root `UserAdministration`, `GovernancePanel`, `OfficialDocuments` са explicit default
re-exports. `App` запазва `LanguageSwitcher`, `Repairs`, `PartCatalog`, `Documents`;
legacy screens имат lazy adapters, за да не влизат обратно в initial bundle.
`CompatibilityImports.test.tsx` проверява тази повърхност. Не добавяйте нова логика в adapters.

## Lazy loading и откази

Всеки голям screen има module-scope `React.lazy`, без нов router или URL поведение.
Sidebar, global search, parts badge, locale и auth bootstrap остават eager.
`PageBoundary` използва `role=status`, `aria-live=polite` и съществуващия превод
„Зареждане…“. Грешка в chunk показва локализирано общо съобщение и „Обнови“,
без raw exception. Sidebar остава използваем; смяна на страницата reset-ва boundary.
Паспортът има затваряем modal дори докато chunk-ът се зарежда или е неуспешен.

PWA cache policy е непроменена: shell и успешно посетените assets се кешират,
API и mutations не се кешират. Няма обещание за offline бизнес операции или
предварително кеширане на непосетени lazy страници; нужен е online достъп до тях.
`ServiceWorker.test.ts` изпълнява реалния `public/sw.js` срещу изолирани browser APIs
и проверява cached chunk bytes, API exclusion и deep-link shell fallback.

## Възпроизводимо измерване

От `frontend/`:

```text
pnpm install --frozen-lockfile
pnpm build
node scripts/measure-bundle.mjs
```

Build генерира `.vite/manifest.json`; измерването следва **всички static imports**,
а не само entry filename. Не са променяни warning threshold или manualChunks.
Baseline е изграден преди рефактора със същия lockfile и toolchain:

```text
pnpm build --manifest --outDir ../.tmp/pr35-shell-qa/baseline-dist
node scripts/measure-bundle.mjs ../.tmp/pr35-shell-qa/baseline-dist
```

| Мярка | Преди | След |
| --- | ---: | ---: |
| Initial JS, bytes | 638 930 | 444 483 |
| Initial JS gzip, bytes | 164 707 | 125 068 |
| Всички JS chunks, bytes | 638 930 | 648 610 |
| JS chunks | 1 | 23 |
| Най-голям JS chunk, bytes | 638 930 | 444 483 |
| Vite >500 kB warning | Да | Не |

Initial JS намалява с **30,43%**, gzip с **24,07%**. Общият JS расте с 1,52%
от разделянето/compatibility/boundaries; това е изрично отчетено, не скрито.
Включително автоматично заредения първи screen: shell + Dashboard са
446 430 bytes / 125 813 gzip; shell + Machines са 454 956 / 128 269.
Catalog chunk 35 805 bytes; transfers 34 487; settings 30 376; repairs 22 011;
passport 15 244; users 13 628; parts 10 572; official registry 5 526.
CSS е byte-identical: SHA-256
`bc0528b6d3e47a0fd622a3278a44ba44e35c3b3b96d2c462b61f514be1ba4ac6`.

## Проверки

Baseline: 78 tests / 16 files; typecheck, lint, production build — PASS.
След извличането: 89 tests / 21 files; typecheck, lint, production build — PASS.
Новите 11 regression tests покриват compatibility exports, deferred/failed imports,
navigation race, audit/report downloads, global search/passport/deep link,
administration permissions/payload и service-worker cache договорите.
Пълният backend run: **302 passed, 2 skipped, 5 deselected** (1135,50 s).
Двата skips са LibreOffice layout случаи; покрити са от отделния 8/8 run по-долу.
Петте deselected PostgreSQL случая са изпълнени отделно и минават 5/5.

Точните команди от repository root (Python: `backend/.venv/Scripts/python.exe`):

```text
python -m compileall -q backend/app backend/alembic backend/scripts scripts tests
python -m ruff check backend/app backend/alembic backend/scripts scripts tests
python -m pip check
python backend/scripts/validate_migration_history.py --require-all-protected
python backend/scripts/validate_authorization_inventory.py
PYTHONPATH=backend python backend/scripts/catalog_v2_validation.py
PYTHONPATH=backend python backend/scripts/build_catalog_translations.py --check
python scripts/verify_release.py --output .tmp/pr35-shell-qa/release
python scripts/audit_dependencies.py python --output .tmp/pr35-shell-qa/python-audit.json
python scripts/audit_dependencies.py frontend --output .tmp/pr35-shell-qa/frontend-audit.json
python -m pytest -q -m "not postgres" --durations=10 --tb=short -o cache_dir=.tmp/pr35-shell-qa/pytest-cache --basetemp=.tmp/pr35-shell-qa/backend-tests --junitxml=.tmp/pr35-shell-qa/backend-test-results.xml
python -m pytest -q tests/postgres --durations=10 --tb=short
python scripts/postgres_smoke_test.py
python -m pytest -q tests/test_original_protocol_layout.py --tb=short
docker compose config --quiet
docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet
docker build --tag assetcore:pr35-shell-qa .
```

Compile/Ruff/pip check, strict migration gate (**21 protected / 0 unprotected**),
authorization (**167 routes / 0 errors**), catalog (**611 rows / 9 sources**),
translations, release verifier и двата dependency audits — PASS (0 findings).
Изолиран PostgreSQL 16: **5/5 concurrency tests**, upgrade/downgrade и encrypted
backup/restore — PASS. Compose и development override — PASS.
Локалният Docker build е блокиран: липсва pipe `dockerDesktopLinuxEngine`;
реалният image/runtime smoke трябва да се отчете от GitHub Docker job.
LibreOffice layout QA: първият допълнителен run е 7 passed / 1 skipped
(конверторът не върна PDF в срока); повторният run със същия portable LibreOffice
завърши **8 passed / 0 skipped**. Не е променян timeout или conversion код.

## Browser QA

Production build, реални API/session/CSRF в изолирана loopback SQLite среда,
провереният seed и временен QA акаунт; без production записи.
Desktop 1440×900; mobile 390×844 и 390×600.
Проверени са login/reload, sidebar и background scroll lock, serial search →
паспорт → същата машина в каталога, реална позиция → modal/sheet и Escape,
repairs/parts/registry/library/users/settings и report action. При 390×600
sidebar се превърта до долните елементи, докато body остава fixed на същата позиция;
изборът на страница го отключва. CUA scroll наблюдението даде timeout, но
последвалата DOM проверка потвърди отделния menu scroll и непроменения body offset.
Проверени са и машинният списък (19), transfer страницата и QR страницата
(19 реални изображения, 19 успешно заредени). Финалният mobile reload възстановява
server-side сесията. Няма записани AssetCore console грешки; след финалния reload
се появиха три грешки `M_ID` от инсталирано browser extension (`chrome-extension://`),
а не от приложението. Extension настройки не са променяни.
Browser download-event наблюдението за технически PDF даде timeout: не се твърди
потвърдено записване на файл от браузъра. Report download click не показа UI/console
грешка; точните download API/payload договори са проверени автоматично.
Registry е проверен с реалния празен seed; populated document actions са покрити
от съществуващите component/backend regressions, без измислени business записи.
Физически touchscreen и инсталирана mobile PWA не се симулират от viewport override;
pointer/touch state-machine regressions се изпълняват в компонентния suite.
