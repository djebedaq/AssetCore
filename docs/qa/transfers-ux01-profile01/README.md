# TRANSFERS-UX-01 + USER-PROFILE-01 — QA доказателства

Всички изображения и протоколи са създадени през действителното приложение в нова временна SQLite QA база. Машините `QA-7`, `QA-8`, `QA-10` и QA потребителите са изрично синтетични тестови записи. Production и провереният регистър с 19 машини не са променяни. Няма merge или deployment.

## Приемане и предаване

- [Двете активни партиди А и Б](issued-batches-a-and-b-1440.png): А е частично върната с прогрес 2/1/3; Б съдържа повторно издадените QA-7 и QA-10 с прогрес 0/2/2.
- [Детайли на партида А](partial-batch-a-modal-1440.png) и [партида Б](reissued-batch-b-modal-1440.png).
- [История по отделни машини](completed-machine-history-1440.png).
- [Една машина с два независими завършени цикъла](one-machine-two-signed-cycles-1440.png).
- [Самостоятелен цикъл и двата архивирани протокола](single-cycle-archived-protocols-1440.png).
- [Телефон: активни партиди](issued-batches-mobile-390.png), [история](machine-history-mobile-390.png), [модал](single-cycle-mobile-390.png).
- [Таблет: активни партиди](issued-batches-tablet-768.png), [история](machine-history-tablet-768.png), [модал](single-cycle-tablet-768.png).

[protocol-bindings.json](protocol-bindings.json) показва отделните cycle ID, machine ID, batch ID, official document ID, version и адреси за архивните PDF/DOCX. Връзките идват от transfer FK и подписните manifests; отварянето не генерира нов документ. Регресионен тест проверява и запазването на оригиналната подписана версия след създаване на коригираща чернова.

Основните табове са точно два. Вторичният избор „Всички партиди и операции“ пази достъпа до отменени връщания и след последващо успешно приключване. Отделен тест проверява обновяването на наличността след отмяна от основния workspace, без двойна заявка.

## Профили

- [Създаване с две имена](create-user-two-names-1440.png).
- [Редакция без презиме](edit-user-without-middle-1440.png).
- [Завършване на профил](complete-two-name-profile-1440.png) и [успешна работа след потвърждението](completed-two-name-profile-1440.png).
- [profile-proof.json](profile-proof.json): `PROFILE_COMPLETE`, две имена и липса на изкуствено правно изключение.
- [Български](tabs-bg-1440.png), [английски](tabs-en-1440.png), [руски](tabs-ru-1440.png).

Браузърната проверка създава двуименен administrator през формуляра, изпълнява задължителната първа смяна на парола, одобрява QA заявка и изтегля действителните официални PDF/DOCX. Backend тестът допълнително изпълнява подписен workflow и сравнява архивните хешове и identity snapshots след редакция на името.

## Документи и проверки

PDF/DOCX примерите и ZIP архивът се публикуват в GitHub Actions artifact `catalog-ux04-browser`, заедно с актуалните изображения и JSON доказателства. Документите са QA резултати от съществуващите одобрени шаблони. Оригиналните контролирани документи не са променяни; лицензиране и KK номерация не са преработвани.

[browser-proof.json](browser-proof.json) отчита пет успешни групи приемателни проверки и нула браузърни изключения. CI в [PR #111](https://github.com/djebedaq/AssetCore/pull/111) е окончателният отчет за последния commit: Frontend, Backend, PostgreSQL, Browser и Docker.

Поддържани команди за повторение:

```text
pnpm --dir frontend typecheck
pnpm --dir frontend lint
pnpm --dir frontend test
pnpm --dir frontend build
python -m pytest -q tests/test_optional_middle_name.py tests/test_transfers_ux01.py --tb=short
python -m pytest -q tests/test_bulk_transfers.py tests/test_transfer_lifecycle_projection.py tests/test_ux_workspace.py tests/test_user_accounts.py tests/test_production_hardening.py --tb=short
python -m pytest -q tests/postgres/test_transfers_ux01_postgres.py tests/postgres/test_transfer_lifecycle_projection_postgres.py tests/postgres/test_concurrency.py::test_two_issue_transactions_create_one_active_transfer --tb=short
python tests/browser/run_transfers_profile01_qa.py
python -m ruff check backend/app backend/alembic backend/scripts scripts tests
python -m compileall -q backend/app backend/alembic backend/scripts scripts tests
python backend/scripts/validate_migration_history.py --require-all-protected
python backend/scripts/validate_authorization_inventory.py
```

Документните проверки изискват LibreOffice. PostgreSQL проверките използват само специалната QA база и произволни мигрирани схеми; runner-ът отказва друга база. Браузърният runner генерира нова локална тестова база и пароли в паметта. Не записва пароли, capability tokens или сесийни заглавки в доказателствата.
