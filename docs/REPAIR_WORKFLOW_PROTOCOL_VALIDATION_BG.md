# Четиристепенен repair workflow и protocol v6 — техническа валидация

## Root cause и корекции

- Старият активен граф съдържаше `WAITING_APPROVAL`, `WAITING_PARTS` и отделен `TESTING`, а completion gate-ът изискваше остарели timestamps/status стъпки. Съществуваща карта в `TESTING` можеше да остане блокирана между стария UI и backend правилата.
- Старият екран държеше едновременно много полета и изпращаше широк payload. При refresh/transition локалната форма можеше да се построи от непълно/старо състояние и да изпрати празни стойности върху вече записани по-късни данни.
- Активният граф вече е точно `ACCEPTED → DIAGNOSIS → REPAIRING → COMPLETED`. Четиристепенният UI изпраща само полетата на избраната стъпка и след save зарежда каноничния `RepairCase` от API. Редакцията на предишна стъпка не включва и не нулира полетата на следващите.
- Обикновеното „Запази“ в `REPAIRING` не отваря финализирането. Изрично `advance_to_final=true` валидира работата и записва проследимо събитие, но запазва DB статуса `REPAIRING`. Единствено „Завърши ремонта и създай протокол“ може да изпрати `COMPLETED`.
- Final completion генерира задължителните DOCX/PDF, repair/machine events и audit, задава approver, `Repair.status=COMPLETED`, `Machine.status=READY` и активния `Цех` в една транзакция. Грешка връща всичко до `REPAIRING`/`REPAIR`.

## Миграция

Alembic revision `20260810_0018_repair_wizard_simplification.py` е PostgreSQL/SQLite compatible и:

- добавя nullable `repairs.diagnostic_cleaning`;
- добавя nullable legacy-compatible `repair_participants.minutes_worked` и check `NULL OR > 0`; новият API изисква положително време;
- нормализира `WAITING_APPROVAL → DIAGNOSIS`;
- нормализира `WAITING_PARTS → REPAIRING` само при записана работа/ремонтни минути, иначе към `DIAGNOSIS`;
- нормализира `TESTING → REPAIRING`, без да променя test полета, събития, части, участници, приложения или история.

Downgrade премахва новите колони/constraint, но умишлено не измисля обратно стар legacy статус. Migration тестът създава всички три legacy пътя преди upgrade и проверява точната нормализация и запазването на test/participant данните.

## Участници и времена

Всеки нов допълнителен участник има `minutes_worked`. UI приема часове и минути и изпраща един положителен integer; double click е защитен във frontend и от уникалния repair identity индекс. `participant_total_minutes` е отделен сбор. Stage сборът остава `diagnosis_minutes + repair_minutes + testing_minutes`; календарните timestamps не се представят като труд.

## Използване на референтния документ

Външният `Топтоптоп.docx` е прочетен структурно и рендериран само за съдържателна/визуална референция. Неговият SHA-256 е `1D92C2FC6EE6EC4BC367F83F1140DA86BC100963BE58C7F4542FB59EEEE69201`. Той не е модифициран и не е добавен в Git. Примерните хора, машина, части, дати и текстове не са копирани като AssetCore бизнес данни.

Repair v6 следва полезното разделение на приемане, диагностика и извършен ремонт, но използва собствения approved AssetCore transfer v3 фирмен header. BG/EN/RU executable template SHA-256 са:

- BG: `89231F723DC6184F4A10A8F8682E59BA96F883D23087AD1008FC78F6D4673929`;
- EN: `35A383F7D269E57BFE6F310C864BADB422F581D13E321E2B19A26FE2F70B6E89`;
- RU: `BA786E2E86E18130BEF3DBE4A906E08F900416F87E636F439A0C4A70DFFD92D5`.

## Document QA от 2026-08-10

`backend/scripts/document_qa.py` генерира в изолирана in-memory SQLite среда issue, return, repair и part-request DOCX/PDF. Реалният repair sample съдържа diagnostic cleaning, test method/pressure/leak result, един QA participant с 55 минути, stage total `2 ч 5 мин` и participant total `55 мин`.

- DOCX SHA-256: `4C8A9F1456B30A96BFF7B7A922BC56D2A7DD84F256A46BB71A3646C006007212`;
- PDF SHA-256: `F2D3DA9FE4C4C809657D90683D049B7E2FAD7432836EC40CC587A28E83D2885F`;
- 1 portrait A4 section, 24 tables, 3 PDF pages;
- няма unresolved placeholders; кирилицата присъства в DOCX и PDF;
- трите страници са рендерирани с LibreOffice/Poppler и прегледани визуално в original resolution: header-ът и таблиците са цели, няма clipping, overlap, orphan title, празна случайна страница или повредена кирилица;
- participant редът, stage total и participant total са видими и не са отрязани;
- section audit потвърждава A4 portrait и контролирани margins; style lint завършва успешно и отчита очакваното директно таблично форматиране на фирмения шаблон;
- issue/return остават по една страница и техните source/template файлове не са променяни;
- source hashes на контролирания repair reference и parts reference остават непроменени.

Всички QA стойности са само в изолирани временни файлове/база и не са production seed или бизнес история.

## Ръчна browser QA от 2026-08-10

В изолирана SQLite база е изпълнен целият четиристепенен UI поток с реално презареждане между стъпките. Потвърдено е, че обикновеното „Запази“ в `REPAIRING` не отваря финалната стъпка; „Запази и продължи“ я отваря при непроменен DB статус `REPAIRING`; участникът и времевите сборове се запазват; финалното действие създава DOCX/PDF и атомарно задава `COMPLETED`, машина `READY` и location `Цех`. След приключването машина №17 се визуализира като „Налична“ в екрана „Издай“. При viewport 390×844 четирите етапа и индивидуалните PDF/DOCX действия остават достъпни. Изолираната QA карта и потребител не са добавяни в seed, миграция или Git.
