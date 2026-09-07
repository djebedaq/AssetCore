# ASSET-03B — история на жизнения цикъл в машинния паспорт

База: `8bc1218d097de1da7aa150e7015ef8679ab1d7fe` (merged ASSET-03A / PR #70).
Branch: `assetcore-asset03b-lifecycle-timeline-ui`.

## Обхват и източник

Единственият таб „История“ в съществуващия Passport V2 вече чете
`GET /api/machines/{machine_id}/timeline?category=all&page=1&page_size=25`.
Преди показваше `passport.history`; тази frontend визуализация е премахната.
Старото поле остава в backend договора за съвместимост, но НЕ е fallback
при грешка, празен отговор или липсваща връзка.

ASSET-03A BACKEND CONTRACT UNCHANGED

Няма нов endpoint, backend production промяна, schema промяна, миграция
или dependency промяна. Не се променят бизнес операции, права, Observer,
сесии, CSRF, owner, лицензи, подписи, номера, хешове или документи.
Не са променени verified inventory, seed, catalog и controlled sources/templates.

## Отговорности

| Файл | Отговорност |
| --- | --- |
| MachinePassportModal.tsx | Съществуващият модал и табове; собственик на локалния hook; keyed reset при друга машина |
| usePassportTimeline.ts | Lazy GET, текущ category/page, кеш на един изглед, abort/generation guard, ръчен retry |
| PassportTimelineTab.tsx | Read-only списък, филтри, състояния и сървърно странициране |
| timelinePresentation.ts | Изрични категории/източници, status domain и избрани scalar details |
| types.ts | MachineTimelineItem, MachineTimelinePage, TimelineCategory — ASSET-03A shape |
| industrialUi.tsx / i18n.tsx | Допълнени познати event codes и пълни BG/EN/RU преводи |
| styles.css | Само нови passport-timeline класове; съществуващият .timeline не се променя |

Остават шестте нормални таба: Обща информация, История, Ремонти,
Протоколи, Резервни части, Снимки и файлове. Одит остава permission-controlled.
Няма втори History/Passport екран.

## Заявки и живот на състоянието

1. Отваряне на паспорта показва Overview: **0 timeline GET**.
2. Първо отваряне на История: **1 GET**, all / page 1 / page_size 25.
3. Обикновен rerender и Overview → History не презареждат завършената заявка:
   запазват текущия филтър, страница, резултат или грешка.
4. Избор на друга категория изпраща една нова сървърна заявка за page 1.
   Категориите са all, asset, transfer, repair, parts, document.
5. Next/Previous заменят страницата, не append-ват; total/count/page/total_pages
   и has_previous/has_next са сървърни. Няма локално сортиране, deduplication,
   броене на бизнес събития или inference от статуса на машината.
6. Предишни rows/counts се премахват още при нов query context.
   Loading и error са само в таба; геройът и другите табове остават достъпни.
7. Retry е изричен GET за същите category/page/page_size; няма auto retry,
   polling, mutation или replay на workflow операции.
8. AbortController и generation check отхвърлят закъснели успехи/грешки.
   Смяна на таб прекратява незавършения GET; връщането възобновява незавършено
   зареждане. Завършеният резултат остава кеширан.
9. Смяна на machineId пресъздава вътрешното съдържание, връща Overview
   и изхвърля цялото старо timeline състояние. Затваряне изхвърля кеша.
10. Няма global cache, localStorage/sessionStorage persistence или preload на история.
    Кешът е умишлено краткотраен; няма фоново обновяване на вече зареден изглед.

Празната история, празната категория и празна извънобхватна страница са
различни състояния. Никога не се показва „Страница 1 от 0“. При out-of-range
200 се показват действителната поискана страница и наличният брой страници;
Previous остава според отговора на сървъра.

Observer остава на limited-view паспорта без табове, QR и timeline GET.
Ако timeline отговор изрично е limited_view, неговите items също не се визуализират.

## Представяне и достъпност

Времева колона/rail и компактни карти с category icon + текст, заглавие,
реална референция, статус преди/след, оперативно описание и избрани детайли.
Използва се съществуващият locale formatter с дата, час и минути, без глобална
промяна на timezone/date semantics. Липсващата референция се пропуска.

Всичките **44 текущо излъчвани ASSET-03A event codes** имат изричен превод
на BG/EN/RU, включително asset/location, всички repair events/fallbacks,
части, деветте request milestones и canonical/legacy document events.
Неизвестен бъдещ event има безопасно общо заглавие, а не raw code.

Status domain се избира по действителния source:
machine_event/transfer → machine; repair/repair_event → repair
(дори repair_event да е в category parts); part_request* → request;
document → version. FINALIZED не се представя като SIGNED.
RETURNED_FOR_CHANGES е локализиран; непознат човеко-четим статус остава текст.

- Transfer: издаване, заявено връщане и реално връщане са отделни факти.
  Заявено връщане не получава измислен завършен статус. Показват се налични
  location/recipient/condition/result и notes.
- Repair: реални status transitions, condition/problem, test result/pressure/leaks,
  durations и участие — само когато присъстват и са от правилния scalar тип.
- Parts: part number, количество (без промяна на историческата точност), unit,
  source и request milestones, включително PARTIALLY_DELIVERED.
- Documents: съществуващи номера, type/version/version_status/registry category.
  Няма конструирани download/preview URLs, нови документи или fake actions.
  Съществуващите действия остават в „Протоколи“.
- Text се рендерира от React като escaped plain text. Няма raw JSON dump,
  HTML injection, рекурсивни nested objects, неизвестни details или вътрешни IDs
  като операторски детайли. Идентичността на реда е сървърният event_key.

Филтрите са нормални бутони в group с aria-pressed, не втори tablist.
Запазени са keyboard стрелките на PassportTabList. Има видим focus,
live loading/count и alert/error, истински disabled paging buttons.
Статичните карти нямат изкуствен tabindex. Mobile филтрите са поне 44 px високи.

## Локални проверки (2026-09-07)

Командите за frontend са от `frontend/`; Python командите — от repository root,
с наличната изолирана Python 3.12 среда на ASSET-03A.

| Команда | Действителен резултат |
| --- | --- |
| pnpm install --frozen-lockfile | PASS; lockfile/dependencies непроменени |
| pnpm exec vitest run src/features/passport/MachinePassportModal.test.tsx src/RoleNavigation.test.tsx src/shell/ScreenContracts.test.tsx | Untouched baseline: 3 файла / 20 PASS |
| pnpm exec vitest run src/features/passport src/RoleNavigation.test.tsx src/shell/ScreenContracts.test.tsx src/i18n.test.ts | 6 файла / 193 PASS |
| pnpm typecheck | PASS |
| pnpm lint | PASS |
| pnpm test | 40 файла / 424 PASS |
| pnpm build | PASS; 1649 modules, без giant-chunk warning |
| python scripts/audit_dependencies.py frontend --output .tmp/frontend-audit.json | PASS; 350 dependencies, 0 findings/exceptions |
| python -m pytest tests/test_machine_lifecycle_timeline.py -q | 54 PASS; 10 съществуващи dependency deprecation warnings |
| python -m ruff check backend tests scripts | PASS |
| python -m compileall -q backend tests scripts | PASS |
| python backend/scripts/validate_migration_history.py --require-all-protected | PASS; 21 protected, 0 missing/mismatched/unprotected |
| python backend/scripts/validate_authorization_inventory.py | PASS; 170 routes, 0 errors (production build наличен) |
| python scripts/verify_release.py --output .tmp/release-asset03b | PASS; включва inventory/catalog/translations/document/hash checks |
| PYTHONPATH=backend python backend/scripts/catalog_v2_validation.py --json .tmp/catalog-validation.json | PASS; 611 records, 581 positions, 818 hotspots, 237 duplicates, 0 unresolved, 2 not-drawn, 7 kits/84 components, EN/BG 611/611, 9/9 fingerprints |
| git diff --check | PASS |

По време на development първият нов component run беше 18 PASS / 1 FAIL:
тестът очакваше несъществуващия BG текст „Ремонтиране“, вместо съществуващия
status.repairing. Коригиран е assertion-ът, не production преводът.
Първият typecheck на новите тестове откри неправилна test-library option
`exact` и `setSessionUser(null)`; коригирани са към поддържания API.
Първият catalog CLI без PYTHONPATH завърши с ModuleNotFoundError; правилният
repository environment по-горе премина. Погрешно подаденият baseline
`pnpm test -- ...` стартира целия suite и беше прекъснат; не е броен като PASS.
След това е изпълнен правилният focused baseline преди production edits.

Нови frontend проверки: 19 request/component + 145 presentation/i18n = 164.
Покриват lazy/cache, шест филтъра, backend page flags, out-of-range, retry,
no legacy fallback, stale filter/page/machine response, AbortError, Observer,
keyboard, всички 44 event codes × 3 locales, детайли и escaped text.
Оригиналните 11 Passport V2 и останалите screen/role тестове са запазени.
Съществуващият backend timeline suite не е изменян.

Production chunks: initial JS 469.04 kB / gzip 130.54 kB;
lazy MachinePassportModal 30.53 kB / gzip 8.16 kB; CSS 83.76 kB / gzip 16.08 kB.

## Реален браузър и responsive QA

Chromium-базиран Brave през browser automation; локален production `dist`,
не Vite dev server. Реалният ASSET-03A API използва съществуващите pytest
session_factory/seed и timeline_scenarios в отделна disposable SQLite база.
Само local harness подменя authentication dependency за тестовия actor.
Няма production login, production writes или твърдение за нов authentication audit.
Тестовите допълнителни събития/документи са само в ignored .tmp, не в Git.

Проверени: първа/втора страница 25 + 20 от 45; отделни issue/requested/returned;
repair transition с test_passed=false, pressure/leaks/minutes; дълга референция;
дълго plain-text описание; used part + quantity/unit/source; частична доставка;
официални финализирани документи; празна машина и празна document категория;
запазен repair filter при Overview → History; browser console без error/warn.

| Viewport | Document scroll/client | Modal scroll/client | Timeline scroll/client |
| --- | --- | --- | --- |
| 1440×900 | 1440 / 1440 | 1105 / 1105 | 1061 / 1061 |
| 768×1024 | 768 / 768 | 713 / 713 | 669 / 669 |
| 390×844 | 375 / 375 | 320 / 320 | 290 / 290 |
| 390×600 | 375 / 375 | 320 / 320 | 290 / 290 |

Всички стойности са реални DOM измервания в px; 15 px разлика на mobile
е вертикалният browser scrollbar, не хоризонтален overflow. Съществуващият
ред с Passport tabs има собствен локален хоризонтален scroll и е непроменен.
Снимките от четирите размера са прегледани в QA сесията.
Timeline request log съдържа само GET 200; tab cache не добавя заявка.
Проверено е и нулево зареждане преди History в component regression.

## CI и оставаща квалификация

Пълният backend, frontend, PostgreSQL и Docker са authoritative в fresh
GitHub Actions върху новия PR HEAD. Точните SHA/run/jobs се записват в
описанието на PR и финалния отчет след завършването им; стар CI не се зачита.
Пълният backend/PostgreSQL/Docker suite не се повтаря локално за frontend-only
промяната, както изисква задачата. Няма production deployment или тестове
в истинска production база; browser QA е isolated qualification.

Операторска проверка: отворете машина → История → сменете категории →
Next/Previous → друг таб и обратно → затворете и отворете друга машина.
При мрежова грешка използвайте „Опитай отново“; не трябва да има legacy rows,
raw error или workflow mutation. Документните действия остават в „Протоколи“.

QR-01 NOT IMPLEMENTED

PR NOT MERGED
