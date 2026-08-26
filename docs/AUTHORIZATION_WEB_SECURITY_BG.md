# Authorization coverage и web security guardrails

## Детерминиран FastAPI inventory

`backend/app/authorization_inventory.py` обхожда реалния FastAPI dependency graph.
Всеки HTTP метод се класифицира като централизирано `Permission` право,
удостоверен read, точно прегледано special mutation/public изключение, публичен
статичен PWA ресурс или `unclassified`, което блокира CI.

Проверката не използва URL prefix, frontend бутон или предположение по име.
`python backend/scripts/validate_authorization_inventory.py` връща non-zero exit
code при нов незащитен маршрут, непроверено публично изключение или остарял
задължителен allowlist запис. Компилираният production frontend добавя три read
метода към backend-only graph-а: GET/HEAD за `/assets/{path:path}` и GET SPA
fallback. `OPTIONS` се обработва централизирано от CORS middleware само за
конфигуриран origin, позволен method и позволени headers.

## Точно прегледан публичен allowlist

- `GET /api/health` — read-only health probe.
- `POST /api/auth/login` — credential exchange преди удостоверяване.
- `GET /api/signing/{token}` — summary чрез ограничен capability token.
- `POST /api/signing/{token}` — подаване на подпис чрез capability token.
- `POST /api/signing/{token}/confirm` — потвърждение чрез capability token.
- `POST /api/signing/{token}/reject` — отказ чрез capability token.
- FastAPI schema/docs read методите `/openapi.json`, `/docs`,
  `/docs/oauth2-redirect` и `/redoc`.
- Компилираните `/assets/{path:path}` и SPA shell/PWA fallback, когато
  `frontend/dist` присъства. Те не дават достъп до API данни.

Няма публичен wildcard API prefix. Token signing endpoint-ите проверяват точния
подписен token и domain state; публичният route не означава анонимен произволен
достъп до документ или изображение.

## Удостоверени special mutations

Следните операции нямат общо ролево право, защото са по-тесни self/owner домейни,
но винаги имат authentication dependency и вътрешна server-side проверка:

- смяна на собствената парола;
- прекратяване на собствената browser сесия;
- промяна на собствен език и завършване на собствен профил;
- start/end на owner emergency access;
- прехвърляне на owner designation;
- инсталиране на подписан лиценз от owner-administrator.

Точните method/path/name стойности и основанията им са versioned allowlist.
Основният browser договор е PostgreSQL/SQLite-backed opaque session в
`HttpOnly` cookie. Mutating cookie requests изискват session-bound
`X-CSRF-Token`; logout revoke-ва server-side сесията. Legacy bearer е само
изрична development/test CLI съвместимост и е забранен в staging/production.
Пълният договор е в [AUTHENTICATION_SESSION_SECURITY_BG.md](AUTHENTICATION_SESSION_SECURITY_BG.md).

## Ролево покритие

Окончателните роли остават `administrator`, `director`, `mechanic`, `observer`.
Regression тестът свързва точните mutating routes с централизираните права за
машини, issue/return, repair, parts request submit/decision/fulfillment, каталог,
официални документи и корекции, шаблони, потребители и справочни данни.
Съществуващите integration тестове проверяват owner/licence/emergency
ограниченията, observer отказите, mechanic workflow и director approval
границата. Не е открита необходимост от промяна на ролевата матрица.

## Security headers и кеширане

Централизираният `WebSecurityMiddleware` добавя към application и обработените
error responses:

- `X-Content-Type-Options: nosniff`;
- `Referrer-Policy: strict-origin-when-cross-origin`;
- deny policy за camera, microphone, geolocation, payment, USB и serial;
- `X-Frame-Options: DENY` и CSP `frame-ancestors 'none'`;
- `X-Permitted-Cross-Domain-Policies: none`;
- CSP със scripts само от `'self'`, без inline script и без `unsafe-eval`;
- HSTS за една година с `includeSubDomains` само при production конфигурация и
  реален HTTPS request scope.

CSP допуска `'unsafe-inline'` само за styles, защото текущите React progress и
diagram координати използват style attributes. `blob:` е разрешен за images,
media и objects, защото каталогът и удостовереният PDF preview работят с временни
object URLs. Това не разрешава inline JavaScript.

Всички `/api/` отговори, включително login, user/owner/licence/signing/signature,
official documents, audit, preview и download, получават
`Cache-Control: private, no-store, max-age=0`, `Pragma: no-cache` и `Expires: 0`.
Hashed `/assets/` остават `public, max-age=31536000, immutable`. SPA shell,
manifest и service worker са `no-cache`, за да се откриват нови deployments.

## CORS по среда

`FRONTEND_ORIGINS` приема comma-separated explicit origins; при липса се използва
единичният `FRONTEND_ORIGIN`. Origin стойността е само `http(s)://host[:port]` —
без wildcard, credentials, path, query или fragment. Default портът и trailing
slash се нормализират, дубликатите се премахват.

- development/test: конфигурираният Vite origin плюс автоматичен
  `http://localhost:4173` preview origin;
- staging/production: само изрично конфигурираните origins; липсваща explicit
  стойност прекратява старта;
- credentials са разрешени само с exact origin; methods и request headers са
  ограничени до versioned allowlists, включително `X-CSRF-Token` и explicit
  test/CLI `X-AssetCore-Auth-Mode`.

Production не добавя автоматично localhost. Локален full-stack Docker може да
зададе `FRONTEND_ORIGIN=http://localhost:10000` изрично; това не се наследява от
Render или друга среда.
