# REPORTS-01 — приемателна проверка и доказателства

PR: [#112](https://github.com/djebedaq/AssetCore/pull/112). Основа: актуалният при започване `main`, commit `6361905762f7781d1b7d070b8400eb535cce8681`. Branch: `codex/reports-01`.

Точните дефиниции, формули, времеви граници, прагове, права и ограничения са в [методологията](REPORTS_01_METHODOLOGY_BG.md). Последният SHA и окончателните пет CI резултата са в описанието и Checks на PR; този документ не представя чакащ CI като успешен.

## Изолирани QA данни

Браузърният runner създава нова временна SQLite база и сървър само на loopback, мигрирани със съществуващия Alembic head. Проверените 19 seed машини присъстват като непроменена основа. Добавените три машини `REPORTS-QA-1/2/3`, категория `REPORTS-01 QA`, ремонти, издавания и заявки са изрично синтетични и съществуват само в тестовата база. Изображенията са филтрирани към тези машини. Базата, паролите, signing токените и server логовете не се публикуват.

Фикстурата е [reports01_fixtures.py](../tests/reports01_fixtures.py); публичните идентификатори са в [public-fixture.json](qa/reports-01/public-fixture.json). `KK9000` е изрично зададена синтетична одобрена snapshot стойност в QA; аналитичният модул не извиква генератора за KK номера.

## Проверени сценарии

| Сценарий | Доказан резултат |
|---|---|
| А — много ремонти | Една машина, пет отделни ремонта за 90 дни, един неприключен над 7 дни. Едно внимание с всички основания; пет оригинални референции; действителният ремонт се отваря и контекстът на отчета се запазва |
| Б — частично връщане и повторно издаване | Пет индивидуални издавания, три завършени цикъла и две активни издавания в фикстурата, независимо от частично приключената първа партида |
| Б — действителен подписан workflow | Отделният backend тест създава три синтетични машини в изолирана база и изпълнява съществуващите HTTP операции и подписи: преди подпис 0 издавания; след първо издаване 3; след връщане на две 2 цикъла; повторно издаване преди връщане на третата: 5 издавания / 2 цикъла / 3 активни; след вторите връщания: 4 цикъла / 1 активно. Хешовете на вече създадените протоколи остават същите |
| В — забавена доставка | Поръчка отпреди 20 календарни дни; получени 2, сторнирани 2, получен 1; остатък 4 pcs и 5.5 l по две позиции. Единиците не се смесват. Точно 14 дни не е забавяне; 15 дни е |
| Г — сравнение | Две машини с различна история; първата има 2 издавания и 2 завършени цикъла, втората 1 издаване и 0 завършени цикъла; липсващият труд е показан като недостатъчни данни |
| Д — механик | Реален QA login: `reports.view` присъства, `audit.view_operational` отсъства; Reports HTTP 200, Audit HTTP 403, без видим служебен одит. Отделни тестове отнемат permissions на източниците и доказват отказ за детайли |
| Е — експорт | Изтеглени от сървъра Requests PDF и XLSX с период, категория и конкретна машина. Всички отделни показани показатели от XLSX съвпадат с API; KK номерът е същият; датите са типизирани; OOXML е валиден XML ZIP, без формули; PDF е четим с кирилица и страници. Несторнираните доставки присъстват като отделни събития с оригиналната заявка |

Многото събития/части по ремонт не увеличават броя ремонти. Чакащи подписи, отменени издавания и отменени партиди не се броят като окончателни операции. Сторнираните доставки не се представят като получени доставки. Нулевата база няма процентна промяна. История без позиции или времена не се допълва с предположения.

Машините, категориите и официалните документи се отварят чрез съществуващите модули. Не е създаден втори паспорт, нова ежедневна отчетност или паралелна история.

## Изпълнени проверки

| Команда / среда | Резултат при подготовката на QA |
|---|---|
| `python -m pytest -q tests/test_reports01.py --tb=short` | 33 passed преди добавянето на двете проверки за съответствие на snapshot; общо 35 REPORTS-01 случая в следващия ред, включително действителния workflow с подписи |
| `python -m pytest -q tests/test_authorization_web_security.py tests/test_reports01.py --tb=short` | 48 passed; включва съвпадащ експорт HTTP 200, промяна на източника HTTP 409 и успешно повторение след обновяване |
| `pnpm exec vitest run src/features/reports/Reports.test.tsx src/shell/ScreenContracts.test.tsx src/shell/LazyNavigation.test.tsx src/ui/workspace.test.tsx` | 19 passed; включва обяснение и обновяване след отказан остарял експорт, зареждане на избора за сравнение при поискване и запазен контекст |
| `pnpm exec vitest run src/features/passport/MachineEntryActions.test.tsx src/features/qr/QrEntryPermissions.test.tsx` | 27 passed при самостоятелна повторна проверка; при натоварения локален пълен run имаше два временни frontend отказа. Тестовете не са изключвани |
| `pnpm typecheck`, `pnpm lint`, `pnpm build` | Успешни; Vite запазва съществуващото предупреждение за голям основен chunk |
| `python -m ruff check backend/app backend/alembic backend/scripts scripts tests` | Успешно |
| `python backend/scripts/validate_migration_history.py --require-all-protected` | 35 защитени миграции валидни, 0 липсващи/променени/нови |
| `python backend/scripts/validate_authorization_inventory.py` | Валиден inventory; четирите нови GET маршрута са изрично проверени за `reports.view`; мутиращите маршрути остават 154 |
| `PLAYWRIGHT_MODULE=… python tests/browser/run_reports01_qa.py` | Exit 0; 390 / 768 / 1280 / 1440 px, BG/EN/RU, Escape/focus, оригинален ремонт, съхранен контекст, два сървърни експорта |

Първият GitHub CI run доказа Frontend и Docker; Backend имаше 1511 passed, 2 skipped и един отказ за фиксирания брой API маршрути. Очакването е актуализирано за четирите нови защитени GET операции с допълнителни permission assertions. Първият Browser отказ беше от селектор, който включваше SVG иконите на легендата; той вече избира само основните графики. Последващите окончателни резултати за целия код са в PR Checks. Няма промяна на CI, която да изключва проверки или да представя неизпълнени тестове като успешни.

Локалният пълен Windows run `python -m pytest -q -m "not postgres" --tb=short --durations=10` на междинния commit завърши с 1475 passed, 27 failed, 12 skipped; сред отказите са старото route-count очакване и проверки на официалния документен конвертор, който не е наличен локално. Този run не е представен като успешен. Авторитетната пълна регресия е отделният Linux Backend CI с инсталиран LibreOffice; PostgreSQL случаите се изпълняват в отделната мигрирана CI база.

## Изображения от работещото приложение

| Изглед | Изображение |
|---|---|
| 1. Общ преглед — desktop | [1440 px](qa/reports-01/01-overview-desktop.png) |
| 2. Общ преглед — mobile | [390 px](qa/reports-01/02-overview-390.png) |
| Допълнителни размери | [768 px](qa/reports-01/02-overview-768.png), [1280 px](qa/reports-01/02-overview-1280.png) |
| 3. Машини, изискващи внимание | [Секция](qa/reports-01/03-attention.png) |
| 4. Детайли на проблемна машина | [Пет ремонта](qa/reports-01/04-attention-detail.png) |
| 5. Използване на техниката | [Използване](qa/reports-01/05-usage.png) |
| 6. Анализ на повторно издаване | [Индивидуални цикли](qa/reports-01/06-reissue-cycles.png) |
| 7. Ремонти и неизправности | [Ремонти](qa/reports-01/07-repairs.png) |
| 8. Машини с най-много ремонти | [Диаграма](qa/reports-01/08-repair-ranking.png) |
| 9. Заявки и доставки | [Заявки](qa/reports-01/09-requests.png) |
| 10. Забавени заявки | [Оставащи позиции](qa/reports-01/10-delayed.png) |
| 11. Индивидуален анализ | [Машина](qa/reports-01/11-machine-analysis.png) |
| 12. Сравнение между машини | [Сравнение](qa/reports-01/12-comparison.png) |
| 13. Сравнение на периоди | [Предходен период](qa/reports-01/13-period-comparison.png) |
| 14. PDF отчет | [Страница 1](qa/reports-01/14-pdf-page-1.png), [2](qa/reports-01/14-pdf-page-2.png), [3](qa/reports-01/14-pdf-page-3.png), [4](qa/reports-01/14-pdf-page-4.png), [5](qa/reports-01/14-pdf-page-5.png) |
| 15. Excel отчет | [Визуален преглед на действителните XLSX клетки](qa/reports-01/15-xlsx-content.png); това е преглед от OOXML, не screenshot на Microsoft Excel |
| 16. BG / EN / RU | [BG](qa/reports-01/16-language-bg.png), [EN](qa/reports-01/16-language-en.png), [RU](qa/reports-01/16-language-ru.png) |
| 17. Празно състояние | [Без съвпадения](qa/reports-01/17-empty.png) |
| 18. Mobile с активни филтри | [Филтри](qa/reports-01/18-mobile-active-filters.png) |

Файлове: [примерен PDF](qa/reports-01/reports01-filtered.pdf), [примерен XLSX](qa/reports-01/reports01-filtered.xlsx). Програмни доказателства: [браузър](qa/reports-01/browser-proof.json), [експорт](qa/reports-01/export-proof.json), [очаквани API данни](qa/reports-01/expected-export.json).

## Променени файлове и защита на данните

Аналитичен слой: `backend/app/reports/{filters,service,routes,exports}.py`, `labels.json`, `__init__.py`; регистрация в `backend/app/main.py`; право в `backend/app/permissions.py`.

Интерфейс: `frontend/src/features/reports/{Reports,ReportViews,ReportCharts,Reports.test}.tsx`, `reportData.ts`, `reports.css`, `labels.json`; навигация и типовете в `frontend/src/{App,types,i18n}.tsx/ts`; допълнителен незадължителен selection callback в `frontend/src/ui/workspace.tsx`; актуализирани shell contract тестове.

Проверки: `tests/test_reports01.py`, `tests/reports01_fixtures.py`, `tests/postgres/test_reports01_postgres.py`, `tests/test_authorization_web_security.py`, `tests/browser/{run_reports01_qa.py,reports01.mjs,validate_reports01_exports.py,reports01_xlsx_preview.mjs}` и добавен browser сценарий/artifact в `.github/workflows/check.yml`. Документи: този файл, методологията и изброените QA файлове. Пълният точен списък е в [Files changed](https://github.com/djebedaq/AssetCore/pull/112/files).

Финалният diff е проверен специално за `backend/resources`, seed данните, `docs/SOURCE_REGISTER_BG.md` и Alembic историята: няма промени. Съществуващи архивни PDF/DOCX, snapshots и хешове не се променят. Новите бинарни файлове са само изрично означените синтетични QA експорти и изображения. Оригиналният регистър с 19 машини е непроменен. Production не е достъпван; няма deployment или merge.

Реални ограничения: липсващи исторически времена/връзки/позиции; няма надеждна обща класификация на неизправностите; текущите статуси не са реконструкция на минал момент. Ако източниците се променят след показването на отчета, UI експортът изисква обновяване с HTTP 409. Без цени, финансови загуби, моточасове или AI прогнози. Без промени на workflows и без нови ежедневни отчети на механиците.
