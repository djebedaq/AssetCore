# Portable production foundation — PROD-01

База: `19127a5cb3bb290046b2958dcdea556d6b882aa7`. Това е операционен договор,
не извършен production deployment. Windows + Docker Desktop (Linux containers)
и Linux + Docker Engine използват същия image, PostgreSQL и приложение.
Render free blueprint остава само staging. Няма cloud/registry изискване.

## Какво се променя

| Преди | Сега |
|---|---|
| `app → migrate → db` при обикновен Compose start | `app → db`; `migrate` е само explicit `operations` profile |
| `10000:10000` върху всички host интерфейси | `${ASSETCORE_BIND_ADDRESS:-127.0.0.1}:${ASSETCORE_PORT:-10000}:10000` |
| Само двусмислен `assetcore:local` | Production helper изисква exact SHA, clean checkout, OCI revision label и pin-ва immutable image ID |
| Backup-before-prepare само в runbook | Изпълним `upgrade`: stop → backup → verify exact file → prepare → ready → smoke |

Не се променят runtime settings, readiness, business APIs, RBAC, лицензният
формат, schema или frontend. `MIGRATION_STRATEGY=external` остава твърдо зададен
за web. Schema behind отказва web startup; `start` не поправя/мигрира базата.
`python -m app.runtime prepare` продължава да използва съществуващия bounded
PostgreSQL advisory lock, Alembic и canonical idempotent bootstrap.

## 1. Read-only preflight — Windows и Linux

От repository checkout с Python **3.12+** (самият host helper е standard library):

```powershell
python scripts/production_preflight.py --port 10000
```

```bash
python3 scripts/production_preflight.py --port 10000
```

Отчита OS/architecture, cores/RAM, free disk на проверявания checkout drive,
Docker CLI/Compose/daemon, WSL и firmware virtualization на Windows, loopback
port conflict, UTC дата и Git SHA/clean state. Не инсталира, стартира или
конфигурира нищо; не извежда env, username, host name или списък лични файлове.
`null` означава недостъпна проверка, не успех. `clock_sync_verified=false`:
проверете реалната NTP/time синхронизация отделно. Свободно място на checkout
диска не доказва свободно място в Docker Desktop virtual disk/друг backup диск.

Операторът трябва отделно да провери Docker data disk, backup destination,
наличната RAM за LibreOffice + PostgreSQL, sleep/reboot/power policy и надеждно
захранване. Личен компютър, който заспива, не осигурява непрекъсната услуга.
Недостъпен Docker daemon/изключена virtualization е blocker за реален deploy.
Този PR не инсталира Docker, WSL или hypervisor и не променя host настройки.

## 2. Конфигурация и точен release

Изберете review-нат commit и clean checkout. `SHA` по-долу е точният **40-знаков
Git SHA**, не branch име. Попълнете локално `.env` от `.env.production.example`:

```powershell
if (Test-Path -LiteralPath .env) { throw "Запазете съществуващия .env; не го презаписвайте." }
Copy-Item .env.production.example .env
$ReleaseSha = git rev-parse HEAD
python scripts/production_deploy.py build --sha $ReleaseSha
```

```bash
cp -n .env.production.example .env
RELEASE_SHA="$(git rev-parse HEAD)"
python3 scripts/production_deploy.py build --sha "$RELEASE_SHA"
```

Не презаписвайте съществуващ `.env`; Windows copy командата е **само при липсващ
файл**. Попълнете всички празни стойности чрез защитен editor/secret manager,
без echo, shell history, screenshot или `docker compose config` без `--quiet`.
SECRET_KEY и отделният SIGNATURE_ENCRYPTION_KEY са минимум 32 знака. DATABASE_URL
използва URL-encoded паролата на Compose `db:5432/assetcore`. Този първи runbook
умишлено отказва произволен външен DB host; не е remote-database migration tool.
PUBLIC_BASE_URL и FRONTEND_ORIGIN са реалните одобрени HTTPS origins, без path,
wildcard или временен случаен tunnel domain. Съществуващият API допуска plural
FRONTEND_ORIGINS, но този Compose договор използва singular FRONTEND_ORIGIN.

Build проверява exact HEAD и липса на tracked/untracked промени, след което
използва **git archive**, а не dirty/ignored host файловете за build context.
Не включва `.git`, credentials, локални DB или `.env`. Изходът съдържа само SHA
и immutable image ID; запазете ги. Tag е `assetcore:<SHA>`, OCI label е
`org.opencontainers.image.revision`. Повторен build със същия SHA може да има
различен ID заради upstream base image; за пренасяне използвайте **save/load на
съществуващия image**, не rebuild. Не презаписвайте release tag произволно.

`build` не стартира база или приложение. `init/start/upgrade` валидират SHA,
clean source и label отново, pin-ват точния `sha256:…` image ID и използват
`--no-build`/`--pull never` за app. `assetcore:local` остава само developer
convenience, а не production release identity.

Официалният helper използва фиксирано Compose project име `assetcore`, независимо
от checkout директорията. При различно **вече съществуващо** project име подайте
`--project <EXISTING_PROJECT>` към всяка команда; не сменяйте името при upgrade.
Това запазва `<project>_assetcore_pg`. Не използвайте паралелни checkout-и или
двама оператори за същата инсталация. Локалният OS lock спира едновременните
команди в един checkout/project; не е distributed deployment lock.

## 3. Първа инсталация — само празна база

След успешен build и попълнена конфигурация:

```powershell
python scripts/production_deploy.py init --sha $ReleaseSha --confirm-empty
```

```bash
python3 scripts/production_deploy.py init --sha "$RELEASE_SHA" --confirm-empty
```

Проверява липса на existing app container, стартира само `db`, прави read-only
PostgreSQL проверка за **всякакви потребителски relations**, не само machines.
Само върху празна база изпълнява explicit `prepare`, после web, bounded readiness
и read-only `/api/ready`, `/api/health`, HTML shell smoke. Няма backup на празна
база. Existing installation се отказва; не използвайте `init` като upgrade.
При частично неуспешен init не изтривайте volume и не заобикаляйте empty guard:
нужна е отделна проверка/възстановяване от оператор, не сляпо повторение.

Няма публичен трафик или реална login квалификация чрез HTTP loopback: Secure
cookies изискват окончателния HTTPS proxy. Initial password е само bootstrap;
след действителен първи вход и forced password change я премахнете от `.env`.

## 4. Нормален старт/рестарт — без миграции

```powershell
python scripts/production_deploy.py start --sha $ReleaseSha
```

```bash
python3 scripts/production_deploy.py start --sha "$RELEASE_SHA"
```

Допуска само image ID на съществуващия app container. Release change изисква
`upgrade`, дори schema да не се променя. Проверява readiness и shell; при провал
спира app. Ако DB е спряна, първо стартирайте **само db** със същия project/env.
Обикновен `docker compose up` също вече не включва migration service, но не е
заместител на production helper и неговите release/backup проверки.

## 5. Upgrade — изпълним backup/verify gate

Планирайте downtime. Потвърдете, че това е единствената app инстанция и няма
други DB writers; спрете/дренирайте външния ingress. Подгответе защитена backup
директория, writable от operator и container UID/GID `10001:10001`. На Linux
използвайте отделна директория с обща GID 10001 и setgid (режим `2770`), без
world-writable достъп; това се настройва изрично от host администратора. На
Windows Docker Desktop проверете споделянето и ACL на точния mount.

Подайте BACKUP_ENCRYPTION_KEY само в **текущата operational shell** чрез secret
manager (Base64 на точно 32 bytes). Не го добавяйте в production `.env` или web
service. След операцията го премахнете от shell. Не въвеждайте стойността като
CLI аргумент. Използвайте реалния активен operator user ID от текущата база.

В clean checkout на **новия** exact release:

```powershell
$ReleaseSha = git rev-parse HEAD
$BackupHostDir = "<APPROVED_BACKUP_DIRECTORY>"
$ActorUserId = "<ACTIVE_OPERATOR_USER_ID>"
python scripts/production_deploy.py build --sha $ReleaseSha
python scripts/production_deploy.py upgrade --sha $ReleaseSha --backup-dir $BackupHostDir --actor-user-id $ActorUserId
```

```bash
RELEASE_SHA="$(git rev-parse HEAD)"
BACKUP_HOST_DIR="<APPROVED_BACKUP_DIRECTORY>"
ACTOR_USER_ID="<ACTIVE_OPERATOR_USER_ID>"
python3 scripts/production_deploy.py build --sha "$RELEASE_SHA"
python3 scripts/production_deploy.py upgrade --sha "$RELEASE_SHA" --backup-dir "$BACKUP_HOST_DIR" --actor-user-id "$ACTOR_USER_ID"
```

Изпълним ред:

1. Exact clean SHA → immutable image/label → `compose config --quiet`.
2. Един running old app, healthy readiness/shell; read-only existing revision и
   активен audit actor; old/new image конфигурациите трябва да сочат същата база.
3. Запазва old/new image IDs, SHA, UTC и previous Alembic revision в `release.json`
   в нов уникален `upgrade-*` backup подкаталог. Не записва secrets или DB URL.
4. Спира app writers. Старият **immutable image** изпълнява съществуващия
   `backup_database.py --actor-user-id …`, `--no-deps`, operational key, RW mount.
5. Изисква точно един нов `.acbackup`, записва encrypted SHA-256, проверява
   **същия файл** с `verify_backup.py` и RO mount. Проверява, че hash не се е
   променил по време на verify. Това е съществуващият AES-GCM/custom dump формат.
6. Само при успешни backup **и** verify: новият exact image изпълнява
   `docker compose run --rm --no-deps --pull never -T migrate` →
   `python -m app.runtime prepare`.
7. Стартира web от новия pinned ID, изчаква `/api/ready`, проверява liveness и
   HTML shell. Записва `runtime_ready`, **не** „fully commissioned“.

Backup/verify fail → няма prepare; prepare fail → няма нов web start. При
readiness/smoke fail app се спира. Няма автоматично връщане на стар app срещу
евентуално частично мигрирана база. `release.json` пази failed stage за recovery;
CLI умишлено не препечатва Docker/SQL/settings exception с евентуални secrets.
След прекъсване/timeout проверете останали one-shot containers и състоянието на
DB, преди да предприемете recovery; не replay-вайте upgrade на сляпо.

При стара pre-PROD-01 инсталация helper изпраща само read-only state/smoke probe
по stdin към текущия image. Няма инсталиране/промяна на файлове в него.

## 6. Backup, verify и restore отделно

Точните Windows/Linux команди за `backup_database.py`, `verify_backup.py` и
`restore_database.py` са в [BACKUP_RESTORE_BG.md](BACKUP_RESTORE_BG.md). Изберете
същия `--project-name`, `--env-file` и изричен `ASSETCORE_IMAGE=sha256:…` от
операционния запис. Всички one-shot команди са `--rm --no-deps --pull never`.
Restore изисква `--confirm RESTORE_ASSETCORE` и реален активен audit actor.

Има задължителна поне **една encrypted copy извън същия физически диск/host**:
операторски избран external device или одобрено storage, без cloud vendor
предпоставка. Docker volume/папка на същия SSD не са disaster recovery. Пазете
backup key отделно и проверете възстановяване на друга машина/QA база.
Успешен локален upgrade не доказва, че off-host copy е направено.

Съществуващият backup/verify формат зарежда archive bytes в RAM и използва
tmpfs. Текущият operational `/tmp` е 512 MiB. Измерете DB/document размерите и
достатъчната RAM/tmpfs преди production; при недостиг операцията трябва да
спре, не да заобикаля gate. Промяна на тези лимити е контролирана host capacity
настройка. Не обещаваме неограничен backup размер или автоматична retention.

## 7. Rollback/recovery

Запазете exact old image ID, image archive, source SHA, `release.json`,
проверения backup и отделно защитените operational secrets. Не изпълнявайте
`docker compose down -v`, volume prune или произволен Alembic downgrade.
След failed upgrade app остава спрян. Verify → restore rehearsal в отделна DB
→ проверка на historical documents/hashes/signatures → одобрено възстановяване
и стар old image. Restore е разрушителен и изисква отделно потвърждение; helper
не го изпълнява. Задължително запазете и post-failure състоянието за анализ.
Backup snapshot е преди migration и преди audit insert за самия backup;
съществуващият инструмент записва успешния backup audit в live DB след dump.

## 8. Проверена persistence граница

| Данни | Източник в кода | Production съхранение |
|---|---|---|
| Машини, users/sessions, owner/license, workflow и audit | `models.py` | PostgreSQL |
| Machine/repair/request attachments | `MachineAttachment.content`, `RepairAttachment.content`, `PartRequestAttachment.content` | DB bytes |
| Каталожни качени изображения | `PartCatalogImage.content` | DB bytes |
| Generated и official versions | `GeneratedDocument.content`, `OfficialDocumentVersion.docx_content/pdf_content`, snapshot/hash metadata | DB bytes/JSON |
| Индивидуални legacy transfer protocols | `ProtocolDocument.content` и transfer/machine/batch/hash връзки | DB bytes |
| Подписи | `DocumentSignature.strokes_encrypted/image_encrypted` | Криптирани DB bytes; original SIGNATURE_ENCRYPTION_KEY е нужен след restore |
| Качени template versions | `DocumentTemplateVersion.source_content`, `template_engine.source_bytes()` | DB bytes; initial `source_path` сочи controlled image resources |
| Качена technical library/revisions | `TechnicalDocument.uploaded_content`, `TechnicalDocumentRevision.content`; upload routes в `industrial_api.py` | DB bytes; `uploads/...` е логически ключ, не host storage |
| Canonical technical docs/catalog/template sources | fallback read под `backend/resources`; importer/source integrity | Непроменени static release/image ресурси |
| LibreOffice working files | `template_engine.convert_docx_to_pdf()` | Изолиран временен `/tmp`, не business storage |
| Backup/metadata/export, ако операторът ги поиска | existing operational scripts | Изричен външен mount, не app container layer |

Не е намерено задължително външно динамично business-file хранилище в текущите
production upload/generation routes. Няма storage redesign. Optional
`--documents-dir` в backup tools остава за отделно потвърдено external storage,
не е нужно за DB bytes. Named PG volume оцелява при обикновена container
recreation, но не при изрично изтриване на volume/физическия диск.

## 9. HTTPS/proxy и лиценз — още не са реално квалифицирани

Публичният TLS се терминира от бъдещ одобрен reverse proxy/tunnel. App остава
непубличен loopback по default. При container proxy изберете вътрешна мрежа и
точния непосредствен peer; loopback на host не е loopback на друг container.
TRUSTED_PROXY_IPS управлява application client-IP trust за rate limiting;
FORWARDED_ALLOW_IPS управлява Uvicorn forwarded scheme/header trust. Не са
взаимозаменяеми. Не задавайте `*` или broad guessed network. Проверете реалния
peer и HTTPS scheme, HSTS, secure session/CSRF, CORS, QR/deep link и PDF preview
през окончателния proxy. Никога не публикувайте/proxy-вайте PostgreSQL.
Няма router forwarding, UPnP, случаен tunnel, public unauthenticated API или
Cloudflare конфигурация в този PR.

Runtime ready **не е** full-write licensed production. Enforcement остава
включен; legitimate expired/read-only лиценз не убива `/api/ready` или
разрешените login/read/export/backup/install операции. При първоначална
инсталация owner със завършен профил трябва да инсталира intended production
signed envelope и изрично да провери installation/domain/environment,
подпис/entitlements, срок и статус/write capability в „Настройки“.

Discovery: има license verification/install и операторски инструкции, но няма
production issuer utility в `scripts/` или backend. Издаването е следваща
самостоятелна задача на правоносителя. Не генерирайте issuer private key в
app/container/DB/browser/production `.env`. До реален verified intended license
и HTTPS QA: **NOT FULLY COMMISSIONED**. Disposable crypto в CI е само QA.

## 10. Личен Windows host → фирмен Linux host

1. Изберете exact running image ID/SHA и запазете `docker image save --output
   <IMAGE_ARCHIVE> assetcore:<SHA>`; проверете SHA-256 на архива след пренасяне.
2. Запазете същия clean source/release contract (offline Git bundle е допустим),
   encrypted verified off-host backup и секретите отделно. Няма GitHub runtime.
3. На Linux с compatible CPU/image architecture изпълнете read-only preflight, `docker image load --input
   <IMAGE_ARCHIVE>` и сравнете **точния** image ID/OCI revision, не само tag.
4. Подгответе защитената конфигурация, PG volume и restore rehearsal. Запазете
   INSTALLATION_ID и SIGNATURE_ENCRYPTION_KEY. Промяна на лицензирана инсталация/
   domain изисква потвърждение от правоносителя, не дублиране на лиценз.
5. Изпълнете отделно одобрения restore/HTTPS/license commissioning план; спрете
   старите writers преди cutover. Няма едновременно независимо production
   писане на двата host-а. Същият image/data model, без пренаписване на app.

## Qualification boundary

При qualification наследеният `js-yaml 4.3.1` (само ESLint tooling) блокира
security gate с HIGH advisory. Единствената frontend lockfile промяна е
`js-yaml 4.3.2` и официалният му integrity hash; няма UI/runtime dependency
промяна, нов exception или отслабване на audit policy. Вижте `SOFTWARE_BOM.md`.

Фокусираните tests проверяват Compose/env/release/backup fail gates и read-only
preflight. Docker CI добавя реален **изолиран** Compose PostgreSQL init/start/
backup/verify/prepare/readiness rehearsal; fixture secrets/users не се записват
в production или repository. Existing PostgreSQL migration/restore/concurrency
job се запазва. Това не доказва конкретен физически host, proxy или камера.

- Schema migration: **NONE**; 21 protected revisions са непроменени.
- REAL HOST DEPLOYMENT = **NOT EXECUTED**
- PUBLIC HTTPS TUNNEL = **NOT EXECUTED**
- PHYSICAL QR SCAN = **NOT EXECUTED**
- PARTS-DOC-01 = **NOT IMPLEMENTED**
