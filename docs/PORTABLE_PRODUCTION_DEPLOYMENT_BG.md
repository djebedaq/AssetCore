# Portable production foundation — PROD-01

База: `19127a5cb3bb290046b2958dcdea556d6b882aa7`. Това е операционен договор,
не извършен production deployment. Windows + Docker Desktop (Linux containers)
и Linux + Docker Engine използват същия image, PostgreSQL и приложение.
Render free blueprint остава само staging. Няма cloud/registry изискване.

След внедряване на PROD-05 нормалните операторски операции използват
[`production_manager.py`](../scripts/production_manager.py), описан в
[раздел 11](#11-prod-05--операторски-manager-за-последващи-обновявания).
Ниското ниво и процедурите за първоначално внедряване/recovery остават по-долу.

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
`upgrade`, дори schema да не се променя. След release guard helper-ът изпълнява
`docker compose start db` за **съществуващия** PostgreSQL container и проверява
read-only неговия health статус до 120 секунди (съвместимо и с Compose 2.x без
`start --wait`). Изчаква healthy база преди DB probe и app start/readiness. Възстановява
и едновременно спрени app/db, без отделна ръчна DB команда. При failed DB health
не продължава към app. Няма migrate, prepare, seed, schema change, image build или
pull на нов app release. Проверява app readiness и shell; при провал спира app.
Липсващ container не се създава от DB start — първа инсталация остава explicit init.

PostgreSQL и app са с `restart: unless-stopped`: след рестарт на host/Docker daemon
Docker възстановява услугите, ако не са били изрично спрени. Ръчно спрени услуги
се възстановяват чрез горната официална start команда. PG volume и private network
са непроменени. Вижте [Compose start](https://docs.docker.com/reference/cli/docker/compose/start/)
и [Docker restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/).
Обикновен `docker compose up` също вече не включва migration service, но не е
заместител на production helper и неговите release/backup проверки.

## 5. Upgrade — изпълним backup/verify gate

Планирайте downtime. Потвърдете, че това е единствената app инстанция и няма
други DB writers; спрете/дренирайте външния ingress. Подгответе защитена backup
директория, writable от operator и container UID/GID `10001:10001`. На Linux
използвайте отделна директория с обща GID 10001 и setgid (режим `2770`), без
world-writable достъп; това се настройва изрично от host администратора. На
Windows Docker Desktop проверете споделянето и ACL на одобрената родителска
директория. Helper създава уникалния `upgrade-*` подкаталог с обикновен
`mkdir()`, който наследява нейния ACL, без `chmod` или допълнителни grants.
Windows `mkdtemp()` използва `mkdir(0700)`; при съвременен Python този режим
заменя наследения ACL с ограничен ACL, а последващ `chmod(0770)` не го
възстановява. Не добавяйте `Everyone`/world-writable права. На POSIX остава
`mkdtemp()` с изричен `0770` и наследената от setgid parent група.

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
3. Read-only preflight изисква PostgreSQL server и tools major 16 за избрания
   backup image и target image преди спирането на writers.
4. Създава нов уникален `upgrade-*` backup подкаталог и проверява точния RW
   bind mount чрез избрания **immutable backup image**. Пробата създава, прочита
   и изтрива само временен `.mount-probe-*` файл; няма `.acbackup`, DB достъп,
   Compose environment или подадени secrets. Изпълнява се с `--network none`,
   `--read-only`, UID/GID `10001:10001`, `--cap-drop ALL` и
   `--security-opt no-new-privileges:true`. При грешка в създаването, mount,
   записа/прочитането или почистването helper отказва **преди stop writers**.
   Запазва old/new/backup image IDs, SHA, UTC и previous Alembic revision в
   `release.json`, без secrets или DB URL; отказ при този запис също е преди stop.
5. Спира app writers и отново валидира DB състоянието. Старият **immutable image** изпълнява
   `backup_database.py --actor-user-id …`, `--no-deps`, operational key, RW mount,
   освен при строго ограничения първи преход, описан по-долу.
6. Изисква точно един нов `.acbackup`, записва encrypted SHA-256, проверява
   **същия файл** с коригирания target `verify_backup.py
   --require-postgres-compatible` и RO mount. Освен AES-GCM и checksum изисква
   действителен PG16 custom dump, PG16 restore tool и целеви PG16 сървър.
   Проверява, че hash не се е променил по време на verify. Това е съществуващият
   AES-GCM/custom dump формат.
7. Само при успешни backup **и** verify: новият exact image изпълнява
   `docker compose run --rm --no-deps --pull never -T migrate` →
   `python -m app.runtime prepare`.
8. Стартира web от новия pinned ID, изчаква `/api/ready`, проверява liveness и
   HTML shell. Записва `runtime_ready`, **не** „fully commissioned“.

Backup/verify fail → няма prepare; prepare fail → няма нов web start. При
readiness/smoke fail app се спира. Няма автоматично връщане на стар app срещу
евентуално частично мигрирана база. `release.json` пази failed stage за recovery;
CLI умишлено не препечатва Docker/SQL/settings exception с евентуални secrets.
След прекъсване/timeout проверете останали one-shot containers и състоянието на
DB, преди да предприемете recovery; не replay-вайте upgrade на сляпо.

При `stage=recovery_directory_creation` или `stage=recovery_directory_qualification`
writers още не са спрени и няма backup/prepare. Helper използва контролиран код
`recovery_directory_creation_failed`, `recovery_directory_qualification_failed`
или `recovery_metadata_write_failed`; CLI показва само failed stage, без суров
Docker/OS exception.
Проверете ACL/shared group и Docker достъпа до одобрения parent; не преизползвайте
стар неуспешен `upgrade-*` подкаталог. Пробата проверява текущата mount/write
възможност, но не гарантира свободно място за целия backup или бъдеща промяна на
правата; реалните backup/verify проверки остават задължителни.

При стара pre-PROD-01 инсталация helper изпраща само read-only state/smoke probe
по stdin към текущия image. Няма инсталиране/промяна на файлове в него.

### Първи преход от известния PROD-03A baseline с PG17 tools

Обичайният upgrade продължава да прави pre-migration backup със стария image.
Той отказва, ако този image няма PG16 tools; не преминава автоматично към
target image при несъвместимост. Това пази бъдещи upgrades от използване на
нов application код срещу произволна стара schema.

Само за известния release `1de39f50dcd2d05fd298a6ea6a52ecca1e9ef160` и immutable
image `sha256:1cd58e1157504009af17e06d1830a05dddcf213d4371e30ed6142eac5249263a`
е предвиден изричният аргумент `--pg16-baseline-bridge`. Добавете го към
официалната `upgrade` команда след build на одобрения коригиращ release.
Този режим проверява едновременно:

- точния стар image ID и неговия OCI release label;
- текущата Alembic revision `20260826_0021`;
- непроменените спрямо baseline DB-facing application код, публикувани
  migrations и runtime dependencies в новия committed release;
- PG16 toolchain и реален PG16 сървър за избрания backup/restore operational image.

Само след тези проверки и stop-writers новият **проверен immutable** PG16 image
създава backup на текущата база, преди schema preparation. Следва удостоверена
проверка на същия архив и на действителния dump произход. `release.json` запазва
стария, target и backup image, избрания режим, проверените версии и encrypted
hash за recovery. При липсващо или несъвместимо доказателство няма `prepare`.
Няма обща опция за заобикаляне на версията или за произволен backup image.

PG17-produced архив от предишна репетиция не покрива този gate дори да преминава
AES-GCM/checksum verification. Запазете коригирания PG16 image за отделен QA
restore rehearsal и за евентуално recovery. Старият application image може да
бъде нужен след възстановяване на старата schema, но неговите PG17 restore
tools не са квалифицирани за PG16. Операторът продължава да одобрява отделно
реалното deployment/recovery изпълнение; този correction не го извършва.

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
След failure, настъпил след stop writers, app остава спрян. Отказ преди stop
writers оставя работещото приложение непроменено. Verify → restore rehearsal в отделна DB
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

## 11. PROD-05 — операторски manager за последващи обновявания

PROD-05 се внедрява **за първи път чрез съществуващата ръчна процедура** с
`production_deploy.py`, след независим review, merge и успешен `push` CI върху
точния post-merge SHA. Следващите команди са за вече инсталиран PROD-05 и
съществуваща production инсталация. Те не извършват първоначална инсталация.

Актуалната база при подготовка на PROD-05 (19.09.2026) е
`ab2d4db4fe5f844f90c81156ee8c376e69c005d5`, след PR #76. Операторът е потвърдил,
че това е и текущият live release; тази задача не проверява live инсталацията.
Първото внедряване на PROD-05 се планира от тази база чрез ръчната процедура.
Manager-ът не hardcode-ва базов SHA: бъдещите проверки използват действителния
OCI SHA на работещото приложение и изрично одобрения target.

Host изискванията остават Python 3.12+, Git, Docker и Docker Compose, с вече
одобрения Docker достъп на оператора. Manager-ът използва standard library и
не изисква допълнителен GitHub token. Изпълнява се от постоянния production
checkout. На Linux използвайте `python3` вместо `python`.

### Еднократна локална конфигурация

Заменете всички placeholders с одобрените стойности за съществуващата
инсталация. Backup parent трябва предварително да съществува, да е абсолютна
директория извън checkout, без symlink и с правилните ACL/shared-group права
от раздел 5; на POSIX world-writable parent се отказва. Actor ID е реален
положителен ID на активен audit оператор; не използвайте примерен или измислен
потребител. Project е точното **вече съществуващо** Compose project име.

```powershell
python scripts/production_manager.py configure --backup-dir "<APPROVED_ABSOLUTE_BACKUP_PARENT>" --actor-user-id <ACTIVE_OPERATOR_USER_ID> --project <EXISTING_COMPOSE_PROJECT> --public-origin "<APPROVED_HTTPS_ORIGIN>"
```

`--public-origin` е по избор за инсталации без публична проверка. За инсталация
с публичен HTTPS достъп го конфигурирайте изрично: публично DNS име с HTTPS на
порт 443, без credentials, path, query или fragment. IP адреси, нестандартен
порт и имена с локални суфикси се отказват; завършващ `/` се нормализира.
Manager-ът добавя точно `/api/ready`. Не използвайте временен или неодобрен
адрес. Локалният порт се установява от действителния
loopback-only Docker binding, без подразбиращ се installation-specific порт.

Единственият локален конфигурационен файл е `.assetcore-operator.json`, включен
в `.gitignore`. Съдържа точно `version`, `backup_dir`, `actor_user_id`, `project`
и `public_origin` (`null`, ако опцията е пропусната); непознати/secret полета
се отказват. Повторно configure не допуска смяна на записания Compose project;
това изисква отделна процедура.
Файлът не съдържа backup key, DB credentials, application/signature keys или
лицензен материал. Не го commit-вайте и не копирайте `.env` в него.
Съществуващият `.env` остава в постоянния checkout; manager-ът не чете и не
копира съдържанието му. Guarded executor/Compose продължават да използват
същата защитена конфигурация по съществуващия договор.

### Ежедневни команди

```powershell
python scripts/production_manager.py status
python scripts/production_manager.py restart
python scripts/production_manager.py update --sha <EXACT_APPROVED_40_CHAR_SHA>
```

`status` е read-only. Показва Docker наличност, app и DB running/health статус,
точния immutable app image ID, OCI release SHA, checkout SHA/clean state,
локална readiness и публична readiness при конфигуриран origin. `null` означава
недостъпна проверка, не успех. При неуспешна задължителна проверка командата
връща ненулев exit code, без да променя услугите. Отговорите
се свеждат до разрешени status/code полета; няма container environment, DB
URL, сурови HTTP тела, licence payload, credentials или вътрешни пътища.

`restart` използва guarded `production_deploy.py start` за съществуващия
release и контейнери. Не build-ва, pull-ва, мигрира, създава база/volume или
сменя image. Несъответствие между checkout SHA, OCI revision и разрешения
immutable image води до отказ; смяната на release изисква update. Readiness и
post-start smoke проверките от раздел 4 остават задължителни.

### Одобрено обновяване към точен SHA

`--sha` е задължителен: точно 40 малки hexadecimal знака. `main`, `latest`,
съкратен SHA, непознат commit, downgrade и несвързана история се отказват.
Няма „обнови до най-новото“, автоматично/scheduled deployment, `--force` или
`--skip-ci`. Операторът получава одобрения SHA от review/release процеса.

Manager-ът изпълнява следната последователност:

1. Взема host operator lock и съществуващия lock на guarded executor за
   checkout/project. Валидира локалната конфигурация, read-only текущото
   състояние, чистия Git checkout и identity на origin като официалното
   `djebedaq/AssetCore` repository. Друг оператор не може паралелно да изпълни
   manager update/restart за същата инсталация. Това не е distributed lock;
   отделни host-ове не трябва да имат едновременни writers към една база.
   Windows използва global named mutex между процеси/акаунти и отказва при
   недостъпно заключване; low-level checkout/project lock остава общ с ръчния executor.
2. Fetch-ва официалния origin, установява точния target commit в одобрената
   `origin/main` история и доказва forward ancestry от текущия running release.
   Локални tracked/untracked промени се отказват; те не участват в build.
3. Чрез публичния GitHub API проверява `Build check` workflow за **същия exact
   SHA**: `event=push`, `head_sha=<TARGET_SHA>`, `status=completed`,
   `conclusion=success`. Всички jobs `backend`, `frontend`, `postgres` и
   `docker` трябва също да са completed/success за текущия attempt на последния
   подходящ run; по-стар успешен run не прикрива по-нов failed/pending run.
   PR CI за друг SHA не е
   deployment qualification. При липсваща, pending, failed или недостъпна
   информация няма build или downtime.
4. Представя текущия и target SHA, CI run identity, задължителния backup и
   очакваните deployment фази. Операторът въвежда точно
   `APPLY <FULL_40_CHAR_SHA>`. Отказ или друго въведено потвърждение прекратява
   операцията **преди промяна на checkout, build или stop writers**.
5. Иска `BACKUP_ENCRYPTION_KEY` чрез интерактивен prompt **без echo** и изисква
   валиден Base64 на точно 32 decoded bytes. Няма fallback към видимо въвеждане.
   Ключът не се поставя ръчно в PowerShell environment, CLI аргумент, config,
   `.env`, log или `release.json`. Предава се само в environment на child
   операцията, която го изисква, и се премахва възможно най-рано; не се запазва
   в Credential Manager/keychain. Невалиден ключ прекратява преди target
   preparation и downtime.
6. Подготвя чист detached checkout на точния target SHA и build-ва чрез
   съществуващия `Deployment.build`/`git archive` договор. Потвърждава immutable
   image ID и OCI revision срещу одобрения SHA **преди stop writers**.
7. Извиква съществуващия guarded `Deployment.upgrade` с точния SHA, project,
   approved backup parent и active actor ID. Остават authoritative всички
   проверки от раздел 5: PG16 toolchain, backup-directory ACL/mount проба и
   recovery record преди stop; stop writers → stopped-state revalidation →
   точно един AES-GCM `.acbackup` → SHA-256 и target strict PG16 verify на
   същия непроменен файл → explicit prepare → readiness и smoke. Нормалният
   manager не предлага и никога не подава `--pg16-baseline-bridge`.
   CI се проверява повторно след build, преди guarded upgrade; нов pending или
   failed rerun през това време прекратява операцията без stop writers.
8. Независимо сверява running image ID с току-що построения ID, OCI revision с
   target SHA, app/DB health, локални `/api/ready` и `/api/health`, както и
   публичен `/api/ready`, когато е конфигуриран. Едва тогава връща успешен
   операторски резултат.

### Как се обновява самият manager

Началният процес създава временен snapshot на текущите manager/CI/deploy
модули и изпълнява отделен bootstrap от него. Така промяната на постоянния
checkout не променя изходния код, от който продължава действащият bootstrap.
След SHA-bound потвърждението и валидния ключ checkout става detached на
одобрения target. Нов child процес зарежда `Deployment` от този target и
използва неговите непроменени guarded build/upgrade методи. Parent държи
операторския и low-level lock през цялата операция. Временният snapshot не
включва `.env`, бизнес данни, конфигурационни secrets или target build context;
build context идва само от committed `git archive`.

### Readiness, резултати и действия при отказ

Успешната manager квалификация изисква readiness `service=AssetCore`,
`status=ready`, liveness `status=ok` и `status=pass` за всяка от проверките:

| Проверка | Задължителен readiness code |
|---|---|
| `runtime` | `runtime_ready` |
| `database` | `database_connected` |
| `schema` | `database_schema_current` |
| `configuration` | `configuration_valid` |
| `catalog` | `catalog_integrity_verified` |
| `cryptography` | `cryptography_operational` |
| `license` | `license_evaluated` |

Readiness с `license_evaluated_read_only` или `license_not_applicable`
не покрива този production qualification gate. Това не променя съществуващото
поведение на приложението при изтекъл лиценз: данните и разрешените
read/export/backup операции остават защитени по настоящия договор.

Публичната проверка използва HTTPS с нормална TLS certificate verification и
не следва redirects. Няма Cloudflare API, промяна на tunnel или автоматична
proxy конфигурация. Ако локалният deployment е успешен, но публичната проверка
се провали, manager-ът връща **ненулев exit code / операторска намеса** и пази
успешно стартираното локално приложение. Операторът проверява одобрения origin,
TLS и proxy маршрута; няма DB rollback.

При неуспех на независимата **локална** проверка след upgrade manager-ът
спира само app, ако отново потвърди точния target image. Не стартира стария
image и не връща база/миграции назад. `release.json` запазва резултата от
low-level executor; последвалият операторски резултат показва тази допълнителна
проверка. Запазете и двата при recovery анализ.

Изходът използва стабилни технически stage/result кодове и JSON metadata с
български операторски обяснения. Пазете exact SHA, immutable image ID, CI run
identity, readiness резултатите и recovery directory **basename**, ако е
наличен. Не добавяйте secrets или суров Docker/SQL/HTTP изход към support ticket.
Съществуващият `release.json` остава authoritative recovery запис.

При отказ **преди stop writers** работещото приложение остава непроменено.
Ако checkout вече е преместен на target, source SHA може да е новият, докато
старият app продължава да работи; това е видимо в `status`. `restart` отказва
такова release несъответствие. Не правете сляп retry или произволен checkout.

При отказ **след stop writers** се запазват fail-closed правилата на guarded
executor: няма unsafe old-image restart след потенциално частично prepare,
автоматичен retry или автоматичен rollback. Проверете безопасния failed stage,
`release.json`, backup/verify evidence, останали one-shot containers и реалното
DB състояние. Ескалирайте към отговорния release/recovery оператор и следвайте
отделната контролирана процедура от раздел 7 и
[BACKUP_RESTORE_BG.md](BACKUP_RESTORE_BG.md). Не изтривайте volume, не
изпълнявайте произволен downgrade и не възстановявайте „последния backup“
автоматично. Запазете post-failure състоянието за анализ.

PROD-05 не променя schema, Docker/Compose конфигурация или verified business
материали. Тестовете използват fakes/mocks и временни repositories; не
квалифицират реалния production host, HTTPS route или production secrets.

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
