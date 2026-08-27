# Governance API модуларизация — задача 34

## База и граници

База: `37b9c0ff61e1f08d62de3fd96041638bedb34ca4` от `origin/main`, след merge
на документната модуларизация (GitHub PR #41). Номерът на задачата в correction
серията не е автоматично присвоеният GitHub PR номер.

Преди извличането `backend/app/hardening_api.py` съдържа 1766 реда. След него
съдържа 1309 реда: намаление с 457 реда / 25,9%. Той продължава да сглобява
същия `/api` router с tag `production-hardening`, запазва профилните и
документно-подписните операции и explicit compatibility imports.

Няма нови маршрути, миграция, роля, permission или нова криптографска политика.
Не са променени `main.py`, `permissions.py`, `security.py`, `licensing.py`,
`auth_sessions.py`, `auth_throttle.py`, `web_security.py`, схемите или моделите.
Шаблоните, подписите, каталогът, seed и провереният 19-машинен HPWJ регистър
са извън diff-а.

## Собственост преди / след

Всички изброени функции преди се намират в `hardening_api.py`.

| Нов модул в `backend/app/governance/` | Отговорност |
| --- | --- |
| `owner_routes.py` | Точните owner HTTP signatures, dependencies и response models |
| `owner_service.py` | Ownership lookup/lock, read/audit и transfer с reauthentication, session revocation и audit |
| `emergency_routes.py` | Status/start/end HTTP договор |
| `emergency_service.py` | Времево ограничена процедура, expiry, конфликти, reauthentication и audit |
| `license_routes.py` | Status/validate/install HTTP договор |
| `license_service.py` | Инсталиране, capacity/duplicate проверки, superseded history; използва непроменения `app.licensing` |
| `profile_checks.py` | Съществуващите `_profile_complete` и `_require_complete_profile`, използвани и от документния слой |
| `audit_context.py` | Само съществуващият валидиран `X-Request-ID` correlation helper |

Зависимостите са еднопосочни: `hardening_api` → domain routes → domain services.
Emergency/license използват ownership lookup от `owner_service`, а не owner
HTTP маршрут. Няма import обратно към `hardening_api`, динамичен proxy или
нова обща utils колекция. Старите осем handler имена и шест helper имена
остават достъпни чрез explicit imports. PostgreSQL concurrency тестът
продължава да извиква `app.hardening_api.start_emergency_access`.

Owner read и transfer routers са регистрирани отделно единствено за да се
запази точният стар ред около emergency маршрутите; това не създава различна
authorization политика.

## Преместени маршрути и съществуващо покритие

| Метод / път | HTTP owner | Непроменена dependency / проверка |
| --- | --- | --- |
| `GET /api/owner` | owner routes | `get_authenticated_user` |
| `GET /api/owner/audit` | owner routes | `get_current_active_user` + owner/administrator domain check |
| `POST /api/owner/transfer` | owner routes | `get_current_active_user` + profile, ownership, reauthentication, target validation |
| `GET /api/emergency-access/status` | emergency routes | `get_current_active_user` |
| `POST /api/emergency-access/start` | emergency routes | `get_current_active_user` + profile, owner checks, password/throttle, active conflict |
| `POST /api/emergency-access/{session_id}/end` | emergency routes | `get_current_active_user` + profile, ownership, password/throttle, session ownership/state |
| `GET /api/license/status` | license routes | `get_authenticated_user` |
| `GET /api/license/validate` | license routes | Същият handler и dependency като status |
| `POST /api/license/install` | license routes | `get_current_active_user` + profile, owner/administrator, подпис/лимити/дубликат |

Преди извличането owner transfer, emergency start/status/end и license install
се покриват от `test_production_hardening.py`; cookie reauthentication и session
invalidation — от `test_auth_session_security.py`; role/owner profile/token
правилата — от `test_user_accounts.py`; точните route classifications — от
`test_authorization_web_security.py`; реалният emergency overlap — от
`tests/postgres/test_concurrency.py`.

Новият `test_governance_api_contracts.py` допълва status/validate/audit read
пътищата, всички anonymous/non-owner откази, cookie CSRF за всяка mutation,
точния owner-transfer audit, обезсилването на сесиите и на двамата участници,
bounded throttling за трите reauthentication операции, expiry/end конфликти,
license history и compatibility imports.

`tests/fixtures/governance_api_baseline.json` е заснет преди извличането от
посочения base commit. Съдържа девет реални OpenAPI operation hashes,
единадесет reachable schema hashes, имена, status codes, tags и целия вложен
authentication dependency graph. Не съдържа credentials или бизнес записи
и не се обновява автоматично от тестовете.

## Security / transaction инварианти

- Ролите остават точно четири; designation не е роля и не добавя права.
- Съществуващите, леко различаващи се owner checks не са обединени или
  „подобрени“ при извличането. Редът на проверките и конкретните откази е същият.
- Profile prerequisites, password verification, rate-limit keys/backoff,
  token-version увеличенията и revoke причините остават същите.
- Owner и emergency row locks, flush, commit, rollback и IntegrityError
  преобразуването са преместени със същите тела. Governance services пазят
  собствените съществуващи commits, включително при одитирани откази;
  не се прилага различният caller-owned договор на document builders.
- Ed25519 verification и read-only state evaluation остават в `licensing.py`;
  в приложението не се добавя private signing key.
- CSRF/session dependency веригата и CSP/CORS middleware не се променят.
- Audit actions/details/correlation и неизменяемата document/signature история
  не се пренаписват. Останалите 46 функции в `hardening_api.py` имат същите AST.

## Открит преди извличането read-only HTTP дефект

Разширената baseline проверка откри съществуващ проблем в
`main.py::enforce_license_read_only`: `serialize_license_state()` връща
`datetime` стойности, които се подават направо на `JSONResponse`.
Очакваният `423 license_read_only` в тази branch се превръща в HTTP 500
(`TypeError: Object of type datetime is not JSON serializable`).

Това е възпроизведено върху непроменения base, преди production извличането.
Записващата операция не се изпълнява; canonical state остава read-only,
но HTTP договорът за отказ е дефектен. Този PR **не поправя** проблема, защото
целта му е нулева промяна на поведението. Нужна е отделна изрична поправка.

`test_known_license_read_only_http_serialization_regression` възпроизвежда
проблема като **strict XFAIL, само за TypeError**. При поправка XPASS ще fail-не
suite-а до премахване на маркера. Тестът не е отчетен като passed; останалите
license state/install/history проверки се изпълняват независимо. Нито един
съществуващ тест или CI gate не е отслабен.

## Проверки

От repository root, с project Python environment:

```text
python -m pytest -q tests/test_governance_api_contracts.py tests/test_production_hardening.py tests/test_user_accounts.py tests/test_auth_session_security.py tests/test_authorization_web_security.py
python backend/scripts/validate_authorization_inventory.py
python backend/scripts/validate_migration_history.py --require-all-protected
python -m ruff check backend/app backend/alembic backend/scripts scripts tests
python -m compileall -q backend/app backend/alembic backend/scripts scripts tests
python -m pytest -q -m "not postgres" --durations=10
python -m pytest -q tests/postgres --durations=10
python scripts/postgres_smoke_test.py
python scripts/verify_release.py --output release-verification
```

Frontend: frozen dependency install, typecheck, lint, tests и build.
GitHub CI допълва PostgreSQL migration/backup/restore и реалните production
Docker build, non-root/read-only LibreOffice и health/readiness smoke gates.
Резултатите, skips, XFAIL и ограниченията се отчитат изрично в PR.
