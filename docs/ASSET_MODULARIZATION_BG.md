# PR #32 — модулни активи и справочни данни

База: `123c3324e8f7e96e9192322bda17acf78ce671e6` (merge на PR #31).
Целта е преместване на съществуващ код, без умишлена промяна на API или бизнес поведение.
Няма нови таблици, колони, миграции, зависимости или frontend промени.

## Собственост преди → след

| Преди | След | Отговорност |
| --- | --- | --- |
| `main.py` | `assets/routes.py`, `assets/service.py` | Четене, създаване и редактиране на машина; QR |
| `main.py` | `assets/queries.py`, `assets/serializers.py` | Съществуващ active-transfer read query и ограничен machine изглед |
| `industrial_api.py` | `assets/passport.py` | Read-only сглобяване на паспорт, история и връзки към реални записи |
| `industrial_api.py` | `assets/custom_fields.py` | Типизирани стойности, валидация и audit на машинни полета |
| `industrial_api.py` | `assets/attachments.py` | Прикачване и изтегляне на машинни файлове |
| `main.py`, `industrial_api.py` | `master_data/routes.py`, `service.py`, `serializers.py` | Категории, дефиниции на полета, местоположения и отдели |
| `industrial_api.py` | `attachment_io.py` | Само съществуващата обща проверка на файлови bytes и attachment metadata |
| `industrial_api.py` | `persistence.py` | Само съществуващото преобразуване на commit-time IntegrityError в HTTP 409 |

HTTP адаптерите запазват имената, Pydantic схемите, dependencies, response models и status codes.
Legacy маршрутите остават без industrial tag; останалите наследяват `industrial-platform`.
Старите import имена в `main.py` и `industrial_api.py` са съвместими re-export-и.
Няма промяна на реда на регистрация на маршрутите.

Размер след извличането: `main.py` — 1460 → 1278 реда (−182, 12,5%);
`industrial_api.py` — 3758 → 2789 реда (−969, 25,8%). Общо 1151 реда
по-малко в двата composition модула. Изнесени са 19 HTTP handlers и 8
свързани помощни функции. Сравнение на AST потвърждава непроменени тела на
всичките 27 преместени функции и непроменени 104 останали функции.

Passport модулът само чете transfer/repair/document данни. Издаването, връщането,
ремонтните преходи, заявките за части, подписите, лицензите, owner защитата, шаблоните
и официалните документи остават в досегашните домейни. Транзакционните граници,
audit действията и authoritative status проверките са преместени без преработване.

## Маршрути и покритие, установено преди извличането

Всички пътища са с prefix `/api`. `IP` обозначава `tests/test_industrial_platform.py`,
`UA` — `tests/test_user_accounts.py`, а `AC` — новия `tests/test_asset_master_data_contracts.py`.

| Метод и път | Съществуващо покритие | Допълнителен договор в AC |
| --- | --- | --- |
| GET `/machines` | UA observer; `test_i18n_roles_seed.py` historical status | Подредба, пълни/ограничени данни |
| GET `/machines/{machine_id}` | Няма директен положителен тест | Съвпадение със списъка, observer, 404 |
| POST `/machines` | IP `test_machine_crud_preserves_unknown_serial_and_records_history` | Категория, duplicate 409 |
| PATCH `/machines/{machine_id}` | Същият IP тест | Repair/active-transfer authority, rollback/history, 404 |
| GET `/machines/{machine_id}/qr` | UA observer отказ | Точни PNG bytes и URL с/без public base, 404 |
| GET `/machines/{machine_id}/passport` | IP configurable fields/library; UA observer | 404, active-transfer изглед и observer редукция |
| PUT `/machines/{machine_id}/custom-fields` | IP configurable/required integer | Boolean normalization, category conflict, точен audit |
| POST `/machines/{machine_id}/attachments` | IP `test_machine_attachment_upload_is_hashed_and_downloadable` | Bytes/hash/history и validation откази |
| GET `/machine-attachments/{attachment_id}/download` | Същият IP тест | Bytes, Content-Disposition, nosniff, 404 |
| GET `/categories` | IP configurable/required fields; UA observer | Подредба и fields договор |
| POST `/categories` | Няма директен положителен тест | Запис, отговор, audit |
| POST `/categories/{category_id}/fields` | IP configurable/required fields | Boolean field, audit, 404 |
| GET `/locations` | UA observer отказ | Подредба и запазени деактивирани записи |
| GET `/departments` | IP reference data; UA observer | Подредба и деактивирани записи |
| GET `/admin/reference-data` | IP reference data; UA director/owner | Точно съвпадение с двата справочника |
| POST `/admin/locations` | IP reference data | Нормализация и duplicate договор |
| PATCH `/admin/locations/{location_id}` | IP reference data | Casefold duplicate, деактивация, 404 |
| POST `/admin/departments` | IP reference data | Duplicate code 409 |
| PATCH `/admin/departments/{department_id}` | IP reference data | Деактивация, 404 |

AC проверява допълнително всичките 19 метода/пътя за authentication, observer граници,
точни permission стойности, OpenAPI операции и 17 свързани request/response схеми.
Проверява се и запазването на старите Python import имена на маршрутите.
`tests/contracts/asset_master_data_routes.json` е заснет от горната база **преди**
преместването. Не бива да се обновява автоматично, за да прикрие regression.
Тестовите записи са изрично test-only и се създават единствено в временни test бази.

## Проверки

Изпълняват се focused тестовете по-горе, authorization inventory, strict migration
validator, Ruff/compileall, пълен backend pytest, frontend typecheck/lint/tests/build,
catalog/translation validators, release verifier, реалните PostgreSQL concurrency и
migration/backup/restore тестове и четирите GitHub CI jobs, включително Docker runtime.
Конкретните резултати и ограничения на средата се записват в PR отчета.
