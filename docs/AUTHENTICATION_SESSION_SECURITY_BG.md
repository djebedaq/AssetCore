# Browser authentication, сесии, CSRF и ограничаване на опитите

## Решение и предишен риск

До revision `20260826_0021` browser клиентът пазеше дългоживеещ signed bearer
token в `localStorage` и го добавяше като `Authorization: Bearer` към всяка API
заявка. Това правеше удостоверителния материал достъпен за JavaScript и
увеличаваше последиците от XSS.

Основният browser договор вече е server-managed opaque session. При успешен
вход backend-ът създава криптографски случаен session identifier, записва в
базата само неговия SHA-256 и го връща в `HttpOnly` cookie. React не получава,
не пази и не изпраща bearer token. При reload приложението извиква
`GET /api/auth/me`; върнатият от backend потребител е единственият източник за
текущата роля и права. Старите `assetcore_token` и `assetcore_user` ключове се
изтриват еднократно, без данните от тях да се използват за authorization.

Този модел е подходящ за една same-origin AssetCore PWA: не въвежда OAuth или
външен identity provider, но премахва дългоживеещия credential от browser
JavaScript и остава устойчив при restart и няколко application процеса.

## Durable session state

Миграция `20260826_0021_auth_session_hardening.py` добавя:

- `auth_sessions` — user, SHA-256 на opaque session identifier, SHA-256 на
  session-bound CSRF token, snapshot на `user.token_version`, created/expiry,
  последно наблюдение и revoke причина;
- `authentication_throttles` — HMAC-псевдонимизиран account/source ключ,
  bounded failure window, временно блокиране и timestamp за cleanup.

Raw session/CSRF стойности, пароли и signing tokens не се записват в тези
таблици или в audit log. Expired/revoked session и стари throttle записи се
почистват при успешен login след retention периода, по подразбиране 7 дни.

Успешният login винаги създава нов session и revoke-ва предишната активна
session cookie от същия browser. Logout revoke-ва server-side реда и изтрива
session/CSRF cookies. Session се отказва и при expiry, explicit revoke,
деактивиран потребител или несъвпадение на `token_version`.

Password change/reset, role/activation промяна и owner transfer увеличават
`token_version` и revoke-ват засегнатите активни browser сесии. При собствена
смяна на парола текущият browser получава нова ротационна сесия; останалите
стари сесии не могат да се използват повторно.

## Cookie policy

| Cookie | development/test | staging/production |
|---|---|---|
| `assetcore_session` | `HttpOnly`, `SameSite=Lax`, `Path=/`, explicit `Max-Age`/`Expires`, без `Secure` за localhost HTTP | същите атрибути плюс `Secure` |
| `assetcore_csrf` | `SameSite=Lax`, `Path=/`, explicit `Max-Age`/`Expires`, четима от same-origin frontend | същите атрибути плюс `Secure` |

CSRF cookie не е credential и умишлено не е `HttpOnly`: frontend трябва да го
прочете и да го върне в `X-CSRF-Token`. Истинският session credential винаги е
`HttpOnly`. Не се задава широк `Domain`. Default expiry е 720 минути и се
управлява чрез `SESSION_MINUTES`; `SESSION_COOKIE_SAMESITE` допуска само `lax`
или `strict`.

## CSRF и login origin

При cookie-authenticated `POST`, `PUT`, `PATCH` и `DELETE` backend dependency
изисква `X-CSRF-Token` и сравнява SHA-256 с token-а, свързан точно с текущата
server-side сесия. Липсващ или грешен token връща HTTP 403 със structured code
`csrf_failed`. Read-only `GET` не изисква CSRF. Frontend API client добавя
header-а централизирано и изпраща cookies с `credentials: same-origin`.

Login няма предварителна authenticated session, затова проверява browser
`Origin`/`Sec-Fetch-Site` и отказва cross-site browser login. CLI/test заявка без
browser origin остава възможна. CORS не е заместител на тази проверка.

Еднократното подписване е отделен capability-token workflow. Signing token-ът е
високоентропиен, в базата се пази само hash, има expiry и еднократен
consume/reject lifecycle. Тези публично достижими exact routes не използват
normal browser session и не са погрешно поставени зад CSRF. Съществуващите
document snapshot, hash, consent и signature evidence проверки остават
непроменени.

## Временно ограничаване на опитите

Default login policy:

- account и account+source: 5 неуспеха в 300 секунди;
- общ remote source: 40 неуспеха в 300 секунди;
- прогресивно временно изчакване от 30 до максимум 300 секунди.

Password-change verification, emergency start/end reauthentication и owner
transfer reauthentication използват 5 неуспеха в 300 секунди и същия bounded
30–300 секунди backoff. Няма постоянно заключване на акаунт. Успешният login
изчиства само account/account+source грешките, не общия сигнал за атакуващ
source. Unknown account, грешна парола и inactive account връщат еднакво
съобщение и не разкриват съществуването на потребител.

Ключовете в `authentication_throttles` са HMAC със server secret; email, IP и
парола не се пазят в plaintext. Audit запис се създава при реално активиран
throttle и съдържа само scope имена и периода за изчакване.

`X-Forwarded-For` се използва само когато непосредственият `request.client.host`
попада в изрично зададен `TRUSTED_PROXY_IPS` IP/CIDR списък. При липса на такава
конфигурация forwarding header-ът се игнорира. Не добавяйте произволно
`0.0.0.0/0`; въведете само проверените адреси/мрежи на реалния reverse proxy.

## Bearer compatibility

Legacy bearer е изключен по подразбиране и е забранен от settings validation в
staging/production. Само development/test CLI или автоматизиран тест може
изрично да зададе `BEARER_COMPATIBILITY_ENABLED=true` и да поиска token с
`X-AssetCore-Auth-Mode: bearer`. Това не е browser production path и frontend
никога не изпраща този header. Стар bearer се инвалидира от същия
`token_version` механизъм.

## Операторска проверка

1. Изпълнете `alembic upgrade head`; текущият head е `20260826_0021`.
2. За staging/production потвърдете HTTPS, `Secure` върху двете cookies и exact
   `FRONTEND_ORIGIN(S)`.
3. Оставете `BEARER_COMPATIBILITY_ENABLED=false`.
4. Ако има reverse proxy, задайте само неговите проверени CIDR-и в
   `TRUSTED_PROXY_IPS`; иначе оставете празно.
5. Проверете login → reload → protected mutation → logout → replay отказ, както
   и forced password change с втори предварително отворен browser.
