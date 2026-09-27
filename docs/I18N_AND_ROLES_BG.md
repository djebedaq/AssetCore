# Езици, статуси и окончателна ролева система

## Локализация

Поддържаните езици са `bg`, `en` и `ru`, с български fallback. Всички React екрани използват централни ключове с автоматичен тест за еднакъв набор. Дати и числа се форматират според locale. Превключването не презарежда страницата и се запазва локално; при удостоверен потребител се синхронизира в `users.preferred_language`.

Исторически описания и официални архивни документи не се превеждат и не се пренаписват автоматично. Това пази доказателствената им стойност. Новите UI съобщения, състояния и бизнес конфликти се показват на избрания език.

## Технически статуси

Оперативният машинен workflow използва `READY`, `ISSUED` и `REPAIR`. Активният ремонтен workflow използва `ACCEPTED`, `DIAGNOSIS`, `REPAIRING` и `COMPLETED`; `WAITING_APPROVAL`, `WAITING_PARTS` и `TESTING` остават преводими само за история/legacy snapshots. Партидите използват `ACTIVE`, `PARTIALLY_RETURNED` и `RETURNED`. Ремонтите и заявките за части имат отделни enum домейни. UI показва превод; API интеграциите записват кода.

## Окончателни роли

Нов акаунт може да има точно една от ролите `administrator`, `director`, `mechanic` или `observer`. Старите `admin`, `manager`, `approver` и `viewer` са само миграционни входни стойности и не се приемат от новите API схеми или интерфейса.

| Област / право | administrator | director | mechanic | observer |
|---|---:|---:|---:|---:|
| Пълен регистър и паспорт | да | да | да | не — ограничен изглед |
| Номер, марка, модел, статус и местоположение | да | да | да | да |
| Създаване/редакция/преместване на актив | да | не | не | не |
| Издаване и връщане | да | да | да | не |
| Създаване и изпълнение на ремонт | да | да | да | не |
| Създаване на заявка за части | да | да | да | не |
| Одобрение/отхвърляне на заявка | да | да | не | не |
| Каталог и технически документи | пълен | четене | четене | не |
| Генериране на официални документи | да | да | да | не |
| Оперативен audit и справки | да | да | не | не |
| Пълен технически audit | да | не | не | не |
| Каталог provenance, hotspots и repair kits | да | не | не | не |
| Шаблони, numbering rules, import и настройки | да | не | не | не |
| Управление на director | само system owner | не | не | не |
| Създаване/повишаване/управление на друг administrator | само system owner | не | не | не |
| Управление на mechanic/observer | да | да | не | не |

Авторитетната матрица е `backend/app/permissions.py`. API връща разрешенията в `user.permissions`; frontend-ът ги използва само за навигация и видимост. Всяка операция се проверява отново в backend.

| Permission кодове | administrator | director | mechanic | observer |
|---|---:|---:|---:|---:|
| `users.view`, `users.create`, `users.edit`, `users.activate`, `users.deactivate`, `users.reset_password` | да | да, само mechanic/observer | не | не |
| `users.assign_director`, `users.assign_administrator` | да, но задаването изисква и текущ system owner | не | не | не |
| `assets.view` | да | да | да | да, ограничен отговор |
| `assets.create`, `assets.edit`, `assets.change_location` | да | не | не | не |
| `transfers.view`, `transfers.create`, `transfers.return` | да | да | да | не |
| `repairs.view`, `repairs.create`, `repairs.edit`, `repairs.complete` | да | да | да | не |
| `requests.view`, `requests.create` | да | да | да | не |
| `requests.approve` | да | да | не | не |
| `parts.view` | да | да | да | не |
| `parts.manage` | да | не | не | не |
| `documents.view`, `documents.generate` | да | да | да | не |
| `templates.manage` | да | не | не | не |
| `audit.view_operational` | да | да | не | не |
| `audit.view_full`, `settings.manage` | да | не | не | не |

## Защитен основен администратор

`ASSETCORE_OWNER_EMAIL` определя системния собственик при първоначалното създаване. След това `InstallationOwnership` е авторитетният запис за текущия собственик, включително след прехвърляне. Той е `administrator`, `is_system_owner = true` и остава активен. Може да има няколко потребители с RBAC роля `administrator`, но само един системен собственик. Частичен уникален индекс допуска най-много един owner, а check constraint изисква owner да е активен administrator. При съществуваща база миграцията прекратява работа преди schema промяна, ако owner не може да бъде определен еднозначно.

Стандартният `/api/users` endpoint позволява само на текущия Owner да създава или повишава друг потребител до `administrator`. Задаването изисква едновременно `is_system_owner = true`, `role = administrator` и `users.assign_administrator`; наличието на `ALL_PERMISSIONS` само по себе си не е достатъчно. Новият administrator винаги има `is_system_owner = false`. API не приема клиентска промяна на `is_system_owner`. Owner не може да бъде понижен, деактивиран или редактиран през user-management API и паролата му не може да бъде нулирана от друг потребител. Само в migration revision-а, за legacy съвместимост, `ADMIN_EMAIL` се използва като fallback, когато `ASSETCORE_OWNER_EMAIL` липсва, с предупреждение без отпечатване на стойността. Runtime startup-ът на новата конфигурация изисква изричен `ASSETCORE_OWNER_EMAIL`.

## Обхват на потребителското управление

- Текущият Owner създава и управлява всеки друг `administrator`, `director`, `mechanic` и `observer`.
- Administrator без ownership създава и управлява само `mechanic` и `observer`. Не управлява друг administrator или director и не задава тези роли.
- Director вижда и управлява само `mechanic` и `observer`, включително смяна между тези две роли.
- Mechanic и observer нямат достъп до `/api/users`.
- Никой не променя собствената си роля през потребителското управление. Редакция, активиране/деактивиране и reset следват еднакъв обхват; защитеният текущ Owner е изключен.
- Нормалното управление използва активиране/деактивиране; деактивацията пази всички исторически връзки и незабавно обезсилва токените и сесиите. Текущият системен Owner има отделен защитен workflow за окончателно физическо изтриване (OWNER-DATA-01). Защитени исторически зависимости, включително ownership и audit връзки, могат да блокират изтриването. Текущият Owner не може да бъде изтрит.
- Създаването и reset-ът задават временна парола и `must_change_password = true`. До успешна смяна са разрешени само login, `/auth/me`, logout от клиента и `/auth/change-password`.

| Действащ потребител | Създава / задава роли | Управлява други потребители | Прехвърля ownership / окончателно изтриване |
|---|---|---|---|
| Текущ Owner (`administrator`) | administrator, director, mechanic, observer | всички четири роли без текущия Owner | да, през отделните защитени workflows |
| Administrator без ownership | mechanic, observer | mechanic, observer | не |
| Director | mechanic, observer | mechanic, observer | не |
| Mechanic / observer | няма | няма | не |

Прехвърлянето изисква активен administrator с пълен профил, повторно удостоверяване и основание. Бившият Owner запазва роля `administrator`, става `is_system_owner = false` и губи всички owner-only операции. Новият Owner може да го управлява като обикновен administrator; историческите зависимости продължават да защитават изтриването. Промяна на роля обезсилва токени/сесии и записва старата и новата роля в audit. Прехвърлянето обезсилва токените/сесиите и на двамата участници.

Отделният self-service за попълване на собствен профил остава достъпен и не дава право за смяна на роля, ownership или самоодобряване на изключение за законно име. Редакцията на чужд структуриран профил използва същата обща проверка за обхват като останалото потребителско управление.

## Permission audit — FINAL-AUDIT-FIX-01

Проверени са всички 30 стойности на `Permission` срещу runtime употребите в `backend/app`, извън дефиницията и `ROLE_PERMISSIONS`. `USERS_ASSIGN_ADMINISTRATOR` вече има реална проверка при създаване и промяна на роля, с тестове за разрешен Owner, отказан non-owner administrator и липсващо permission.

Единствената стойност без runtime употреба извън матрицата е `ASSETS_CHANGE_LOCATION` (`assets.change_location`). Тя остава за бъдещо отделно почистване; настоящата поправка не променя разрешенията за активи и местоположения.

## Миграция на legacy роли

Alembic revision `20260801_0004_final_user_roles` преобразува `manager` и `approver` към `director`, `viewer` към `observer`, запазва `mechanic`, превръща съвпадащия legacy `admin` в system owner, а всеки друг legacy `admin` — в `director` с audit запис и migration warning. Връзките към ремонти, заявки, предавания, документи и audit не се променят. Миграцията поддържа SQLite и PostgreSQL и има безопасен downgrade към legacy кодовете.
