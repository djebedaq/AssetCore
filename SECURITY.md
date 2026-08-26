# Сигурност на AssetCore

AssetCore е собственически индустриален софтуер. Не публикувайте уязвимости,
реални инвентарни данни, документи, подписи, лицензи, backup-и или credentials в
публични issues. Изпратете частен доклад до правообладателя по договорения с
клиента защитен канал. Не включвайте пароли, токени, private keys или production
environment стойности в доклада.

## Поддържана граница

Release Candidate се поддържа само с приложени Alembic миграции, PostgreSQL в
production, HTTPS reverse proxy, активен подписан лиценз, отделни случайни
`SECRET_KEY` и `SIGNATURE_ENCRYPTION_KEY`, и owner bootstrap чрез `OWNER_*`.
SQLite е за development и автоматизирани тестове. Production backup се съхранява
извън repository-то, криптиран и с отделно управляван ключ.

## Основни контроли

- Ролите са точно administrator, director, mechanic и observer; owner
  designation е отделно защитено свойство.
- Backend проверява всяко право. Ролево скрит бутон не е security control.
- Browser login използва durable opaque session в `HttpOnly` cookie; raw
  session identifier не се пази в базата или `localStorage`. Authenticated
  mutating requests изискват session-bound CSRF token, а logout и security
  state промени revoke-ват предишните сесии.
- Login и чувствителните password/owner проверки имат bounded database-backed
  throttling без постоянно заключване. Forwarded client адрес се приема само
  от изрично конфигуриран trusted proxy.
- Детерминираният FastAPI authorization inventory блокира CI при нов
  некласифициран маршрут или публично изключение без точно method/path/name
  основание. Пълният договор е в
  `docs/AUTHORIZATION_WEB_SECURITY_BG.md`.
- Няма master password, backdoor, private licence-signing key или дистанционен
  kill switch.
- Подписните strokes и изображения са криптирани; изображенията нямат публичен
  URL и се изтеглят само през permission-protected API.
- Подписаната версия, snapshot-ът и файловите hashes са неизменяеми. Корекцията
  създава нова версия и нови подписи.
- Audit history няма delete endpoint. Backup, restore, owner и license операции
  изискват идентифициран оператор и одит.
- При изтекъл лиценз данните не се изтриват; след grace period се блокират
  записващите операции, а четене, export, backup и валиден авариен лиценз остават.
- Централизиран CSP забранява inline scripts, `unsafe-eval` и framing. Всички API
  и защитени document/signature отговори са `private, no-store`; hashed frontend
  assets запазват immutable cache. HSTS се изпраща само за production HTTPS.
- Staging/production CORS изисква explicit `FRONTEND_ORIGIN(S)`, не приема
  wildcard и не добавя автоматично localhost.
- Production миграциите са отделна one-shot операция с bounded PostgreSQL
  advisory lock; web процесите отказват старт при schema drift. `/api/health`
  не проверява dependencies, а `/api/ready` връща само non-sensitive status
  codes и fail-ва при DB/schema/startup проблем.
- Runtime container-ът е непривилегирован (`10001:10001`) с immutable
  application source. Production-style Compose не публикува PostgreSQL към
  host, прилага `no-new-privileges`, премахва capabilities и ограничава writes
  до explicit tmpfs.

## Преди production

Изпълнете release checklist, PostgreSQL/Docker smoke тест, restore rehearsal в
отделна база и визуална DOCX/PDF проверка с LibreOffice. Правните draft файлове
се одобряват от квалифициран юрист преди договорна употреба.
