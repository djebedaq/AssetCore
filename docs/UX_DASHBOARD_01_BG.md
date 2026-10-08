# ASSETCORE UX & Dashboard 01

Начална база: `8b110eb75444a5e72da65f0ce7e49ca697866e39` (`origin/main`, PR #98).
Един координиран PR, оставен отворен и неслят. Без достъп до production.

## План преди реализацията

| № | Изискване | Реализация и проверки |
|---|---|---|
| 01 | Dashboard: категории и бройки | Общата агрегация на регистъра; тестове за нови/неактивни категории и точен общ брой. |
| 02 | Активни партиди и завършена история | SQL филтри преди странициране; действително завършено издаване и активна връзка; отделен достъп до неподписани/стари записи. Частично и пълно връщане. |
| 03 | Еднократни Детайли | Един разгъваем панел с оригиналните действия, документи и сведения за отделните връщания; без втори диалог. |
| 04 | Ремонти по категории | Регистър HAS_REPAIR_WORKFLOW, SQL търсене, статус, дати, сортиране и страници; оригиналният редактор и протоколи. |
| 05 | Каталог: категория → машина | HAS_PARTS_CATALOG, зависим търсещ селектор, изчистване на несъвместим избор; публикуваният runtime остава същият. |
| 06 | Селектори и скролбари | Общ достъпен combobox с портал, клавиатура, търсене, фокус и Escape; общи умерени стилове за скролиране. |
| 07 | Dashboard анимации | CSS появяване и прогрес, React числов преход, reduced-motion; без отлагане на данните. |
| 08 | Компактни филтри | Общ toolbar и pagination, debounce и защита от остарели отговори; машини, предаване, ремонти, заявки, каталог. |
| 09 | Семантични статуси | Общ компонент с отделни domain mapping, икона и преведен текст; unknown/legacy fallback. |
| 10 | Последна активност | Ограничена SQL проекция на реални предавания, ремонти и заявки; проверки на правата; отваряне на оригиналния запис. |
| 11 | История на машина | Разширяване на съществуващата хронология с оригинални връзки и общи статуси; подреждане, недублиране, права и по-стара история. |

## Архитектурни решения

- Използват се съществуващите технически capability кодове и централизирани права.
- Новите страницирани read endpoints са добавъчни: старите API договори остават съвместими.
- Историческите записи се филтрират по текущата категория на оригиналната машина. Това се обозначава в интерфейса; неизменните документни snapshots не се пренаписват.
- „Всички“ и изричен архивен обхват запазват достъпа до неактивни, неподдържани, некатегоризирани и смесени записи.
- SQL търсене/филтриране/броене преди LIMIT/OFFSET, детерминиран ред и ограничени размери. Детайлите се зареждат при отваряне.
- Запазват се транзакциите, подписването, QR, протоколите, документната библиотека, Catalog Builder и PARTS-DOC.
- Няма свиваем sidebar, attention center или постоянна памет за последния workspace.

## Приемане

Изолирана локална QA база, действителен frontend/backend и Chromium/Edge. BG/EN и RU parity; 1920/1440/1280/900/390 px; клавиатура, дълги списъци, reduced motion, документи и частични връщания.

Резултатите от изпълнените команди, браузърните сценарии и ограниченията се записват след реализацията. Неизпълнени проверки не се считат за успешни.

## Реализирани промени

1. Dashboard получава динамична SQL агрегация на категориите и действителния регистър, включително отделен некатегоризиран остатък. Общият брой се проверява срещу сумата; няма примерни категории или бройки в приложението.
2. Предаването има отделни сървърно страницирани контексти: активни, завършени, чакащи операции и индивидуални записи. Активна е само реално издадена машина със завършено подписване и активна transfer връзка. Завършена партида има поне едно действително издаване, няма активни машини или неподписано издаване и всички издадени машини са върнати. „Записи по машини“ включва и активните стари записи без batch FK, вместо да ги скрива чрез неявен completed-only филтър.
3. Един бутон „Детайли“ разгъва/свива пълния панел. Оригиналните DOCX, PDF, preview, ZIP, отказ на чакаща операция и всяко отделно частично връщане остават достъпни. Дублиращият popup е премахнат.
4. Ремонтите използват capability категории и SQL филтри по идентификатор/номер, сериен номер, протокол, проблем, статус и UTC период; детерминирано сортиране и странициране. Четирите оригинални етапа, участници, части, приложения и генерирани протоколи са запазени.
5. Каталогът изисква категория преди избора на машина. Машините се търсят на сървъра само в съвместимата категория; смяната изчиства неподходящия избор. Съществуващото потвърждение за количката и публикуваният runtime, общите каталози, PDF и hotspots се запазват.
6. Общият `Select` е portal combobox с търсене, избрана опция, фокус, стрелки, Home/End, Enter/Space, Tab и Escape. Panel-ът се позиционира в viewport и над диалози. Общите scrollbar стилове запазват native скролиране и high-contrast поведение; sidebar остава несвиваем.
7. Появяването на Dashboard е 480 ms с ограничено поетапно забавяне; числата се интерполират за 500 ms, а действителните проценти — за 600 ms. Screen-reader стойностите са окончателните числа веднага; reduced-motion изключва движенията.
8. Общият toolbar обслужва машини, предаване, ремонти, заявки и каталог. Търсенето има 250 ms debounce, AbortController и защита от остарели отговори; промяната на филтър връща първата страница. Няма постоянна памет за последния workspace.
9. `StatusBadge` прилага отделни domain mappings за машина, ремонт, заявка и партида. Значението е цвят + икона + преведен текст; waiting/cancel/reject и непознат код са неутрални. Техническите кодове и историческите записи не се променят.
10. Последната активност е ограничена до осем реални събития от canonical issue/return, приемане/приключване на ремонт, подаване/поръчване/доставка на заявка и решения по одобряване. SQL permission filtering предхожда ограничението; няма audit payload, synthetic feed или polling. Връзката отваря конкретния оригинален запис.
11. Хронологията използва съществуващите canonical per-machine източници, стабилни event keys, обратен хронологичен ред и страници. Добавени са връзки към точните ремонти/заявки/предавания и авторизирани документни endpoints; подписите и document bytes не се включват в list отговорите.

## Основни файлове и API

- `backend/app/workspace.py`: шест добавъчни read endpoints, SQL predicates/counts/aggregation и activity projection.
- `backend/app/main.py`: включване на workspace router и добавъчни Dashboard полета.
- `backend/app/transfer_service.py`: SQL предварително ограничаване на return manifests по authoritative issue relationship преди материализация.
- `backend/app/assets/timeline.py`, `timeline_schemas.py`, `official_documents/registry.py`: metadata-only документни връзки в машинната история.
- `frontend/src/ui/Select.tsx`, `StatusBadge.tsx`, `workspace.tsx`, `workspace.css`, `translations.ts`: общи интеракции, филтри и BG/EN/RU ключове.
- `frontend/src/features/{dashboard,machines,transfers,repairs,partRequests,catalog,passport}` и `App.tsx`: интеграция и точно отваряне на записи.
- `tests/test_ux_workspace.py`, `tests/postgres/test_ux_workspace_postgres.py` и `tests/browser/*ux*`: SQL/authorization/domain/browser acceptance.

Новите GET endpoints са `/api/workspace/categories`, `/machines`, `/repairs`, `/requests`, `/batches`, `/transfers` под общия `/api/workspace` prefix. Страниците са с default 25 и maximum 100; category/machine/record identifiers, search, status, период и sort се валидират. Старите mutation endpoints и техните права остават в сила.

Няма schema промяна или нова migration. Използват се наличните индекси и връзки. SQLite и PostgreSQL JSON predicates имат отделни реализации със същата проверка за действителни integer transfer IDs. `stored_status` запазва оригиналния batch код; presentation status се извежда от реалните relationships, без пренаписване на историята.

Категориите се определят от `HAS_TRANSFER_WORKFLOW`, `HAS_REPAIR_WORKFLOW`, `HAS_PARTS_CATALOG` в съществуващия registry. Използват се централните permissions. Архивният обхват включва некатегоризирани/неподдържани записи, а смесените партиди имат изричен обхват. Историята на неактивни машини/категории остава достъпна; creation selectors изискват актуална допустимост.

## Изпълнени локални проверки

| Команда | Действителен резултат |
|---|---|
| `pnpm test --maxWorkers=1` във `frontend` | 577 passed, 60 files; 252.56 s. Единичният worker е локална настройка за ограничените ресурси; CI изпълнява стандартния `pnpm test`. |
| `pnpm typecheck`, `pnpm lint`, `pnpm build` | Успешни. Build има съществуващото предупреждение за основен chunk над 500 KB; security/size gates не са отслабени. |
| `python -m pytest -q tests/test_machine_lifecycle_timeline.py tests/test_ux_workspace.py tests/test_authorization_web_security.py --tb=short` | 77 passed, 15 warnings; 1113.82 s. |
| `python -m pytest -q tests/test_ux_workspace.py --tb=short` след batch status и unbatched legacy проверките | 10 passed, 8 warnings; 41.33 s. |
| `pnpm test src/features/transfers/Transfers.test.tsx src/features/transfers/__tests__/LifecycleHistory.test.tsx --maxWorkers=1` | 7 passed / 2 files; 32.27 s. Последващите typecheck, lint и production build също са успешни. |
| `python -m pytest -q tests/test_production_manager.py::test_windows_host_mutex_blocks_other_processes_without_production_lock tests/test_original_protocol_layout.py::test_transfer_signatures_stay_on_original_a4_page -ra --tb=short` | 1 passed (Windows mutex), 2 skipped (LibreOffice липсва в локалния host); 1.01 s. Тези два layout теста не са отчетени като успешни. |
| `python -m ruff check backend/app backend/alembic backend/scripts scripts tests` | All checks passed. |
| `python -m compileall -q backend/app backend/alembic backend/scripts scripts tests` | Exit 0. |
| `python -m pip check` | Няма несъвместими зависимости. |
| `python backend/scripts/validate_migration_history.py --require-all-protected` | Valid; 31 защитени migrations. |
| `python backend/scripts/validate_authorization_inventory.py` | Valid; 270 routes, 138 mutation routes, 236 permission-protected routes. |
| `PYTHONPATH=backend python backend/scripts/catalog_v2_validation.py` | Valid; 611 records, девет source файла, девет authoritative fingerprints. |
| `PYTHONPATH=backend python backend/scripts/build_catalog_translations.py --check` | Успешен translation gate. |
| `python scripts/audit_dependencies.py frontend` и `python scripts/audit_dependencies.py python` с отделни `--output` файлове | И двата доклада са valid, blocking findings са празни. |
| `python scripts/verify_release.py --output <нова QA директория>` | Exit 0; release manifest, SBOM и контролните DOCX/PDF проверки са успешни. |

Пълният първи локален backend прогон беше прекратен и **не е отчетен като успешен**. Първият локален PostgreSQL прогон завърши с 62 passed, 2 failed и 11 errors: един lock timeout и прекъсване/recovery на отделния QA PostgreSQL server. Причината за прекъсването не е доказана. Локалният cold Docker build беше прекратен при бавна инсталация на системните зависимости и **не е отчетен като успешен**. Пълният backend, PostgreSQL backup/concurrency и production-image build/runtime се проверяват от непроменените четири CI jobs на общия PR; окончателните run URLs и заключения се добавят към PR отчета.

## Реален браузър и доказателства

Създадена е нова isolated SQLite QA база с всички 31 migrations и 19-те верифицирани машини. Само в нея са добавени шест изрично синтетични QA машини и необходимите fixtures. Реалните frontend/backend, Edge, forms, cookies/CSRF, графични подписи, downloads и published catalog се използват без HTTP mocks. Контролираното изчакване за loading screenshot задържа заявката и после я пропуска към действителния backend.

Проверени са BG/EN/RU Dashboard и петте модула на BG/EN при 1920, 1440, 1280, 900 и 390 px; липса на horizontal overflow; long labels; portal в диалог; дълъг списък; клавиатура/focus/Escape; reduced motion; реално празна активност и празни search/timeline резултати. Две подписани частични връщания променят остатъка 2→1→0 и партидата преминава в историята. DOCX/PDF/ZIP/preview остават достъпни. Ремонти в две категории се филтрират, каталогът зарежда published PDF/hotspot, category switch изчиства машината, timeline отваря точния оригинален ремонт. Observer получава limited passport и 403 за недопустим workspace.

Финалният разширен браузърен прогон е успешен: 85 screenshots, `errors: []`. Изрично са проверени transfer category B→нула/A→една активна партида, достъпът до активни индивидуални записи и целият ремонтен процес: приемане → диагностика → ремонт → завършване, участник, реално време, успешен тест, status filter за завършени, повторно отваряне на същия REP запис и действително изтегляне на неговите DOCX/PDF. В Git са включени 21 избрани изображения и SHA-256 manifest; QA DB и credentials не се включват.

И четирите jobs на [CI run 37807535987](https://github.com/djebedaq/AssetCore/actions/runs/37807535987) са зелени: frontend **577 passed**, backend **1135 passed / 3 skipped / 74 deselected**, PostgreSQL **74 passed** плюс encrypted backup/restore и pre-0025 Builder upgrade, Docker — всички production-image build/runtime gates. Production configuration е **17 passed**, release verification — успешен. Backend skips са двата оригинални LibreOffice layout cases и Windows mutex case на Linux; последният е изпълнен успешно отделно на Windows. Новите QA доказателства и legacy поправката са в същия PR; окончателният HEAD и четирите CI conclusions се проверяват отново и се посочват в PR/final отчета.

[CI run 37810866116](https://github.com/djebedaq/AssetCore/actions/runs/37810866116) за окончателната версия на приложението, включително active unbatched legacy достъпа, също е изцяло зелен: frontend **578 passed / 61 files**, backend **1135 passed / 3 skipped / 74 deselected**, PostgreSQL **74 passed**, production configuration **17 passed**, всички Docker/runtime/security/catalog/release gates. Последващият QA commit обновява само browser assertions и снимките: крайните KPI/category counts се сравняват с действителния API след приключване на анимациите, без промяна или изчакване в приложението. Повторният реален браузърен прогон е успешен, със същите 85 снимки и `errors: []`.

Възпроизводимият runner е `python tests/browser/run_ux_dashboard_qa.py`, след frontend build и инсталирани тестови зависимости/Playwright. Credentials и keys се генерират в process memory; не се записват storage state, HAR, trace или DB в Git. Снимките и SHA-256 manifest са в `docs/qa/ux-dashboard-01`; техният README описва действителните сценарии и визуалните корекции.

## Ограничения и оценка

- **Ниска:** съществуващият основен frontend bundle остава над warning threshold 500 KB. Новите controls не добавят UI/animation framework.
- **Ниска, съществуваща архитектура:** timeline агрегира metadata за избраната машина със стабилен брой заявки, след което страницира; не се твърди SQL pagination за всеки отделен canonical timeline source. Историческите списъци на целите модули са SQL paginated.
- **Ниска, съществуващи mutation форми:** bulk issue/return availability и verified part reference selectors запазват оригиналните си reference lists. Новите category/machine/history selectors са сървърно ограничени и searchable.
- **Проверка, изискваща резултат:** локалните спрени/неуспешни backend/PostgreSQL/Docker прогони не заменят задължителните пълни CI jobs. PR не е готов за финално приемане преди всички да са зелени.

Production не е използвано, разглеждано, променяно, мигрирано, рестартирано или deploy-вано. Seed данните, source register, original binary документи, audit/transfer/document history и Catalog Builder/PARTS-DOC source material не се редактират. Новите PNG файлове са само QA доказателства. PR остава отворен за независим review и не се merge-ва.
