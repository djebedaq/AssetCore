# Backup и restore

Архивът включва PostgreSQL custom dump, manifest и по избор външно document
storage. Всички генерирани документи/подписи, съхранени като DB bytes, влизат в
dump-а. Архивът се проверява с SHA-256 и се шифрова/удостоверява с AES-256-GCM.

Преди всяко production schema upgrade изпълнете backup и verify, а периодично —
restore rehearsal в отделна база. Едва след успешната проверка изпълнете
one-shot `python -m app.runtime prepare`. Не приемайте успешен `/api/health` за
доказателство за backup или актуална schema; използвайте `/api/ready` и отделния
backup manifest.

## Production Compose one-shot процедура

Стандартният production image съдържа само минималните operational entry points
за backup, verify и restore. Те се стартират чрез съществуващата `app` услуга,
която запазва фиксирания потребител `10001:10001`, read-only root filesystem,
tmpfs `/tmp`, `no-new-privileges`, dropped capabilities и вътрешната Compose
мрежа. Нормалната web команда се заменя само за конкретната one-shot операция.

Преди командите:

1. production `.env`/secret manager трябва вече да предоставя точния
   `DATABASE_URL` и останалата задължителна конфигурация за `app`;
2. database услугата трябва вече да работи и да е достижима по вътрешната
   Compose мрежа;
3. създайте отделен защитен каталог `<BACKUP_HOST_DIR>`, writable за UID 10001;
4. задайте `BACKUP_ENCRYPTION_KEY` в текущата operator shell чрез secret manager.
   Стойността е Base64 и трябва да декодира точно 32 bytes;
5. не записвайте ключа в Dockerfile, Compose YAML, tracked `.env`, backup
   каталога или command аргумент. `-e BACKUP_ENCRYPTION_KEY` предава само името
   и не добавя ключа към общата environment конфигурация на web услугата.

Не стартирайте database/migration dependency като част от backup командата.
`--no-deps` е задължително: така pre-migration backup не може неволно да
стартира `migrate`. Не правете `/app` writable, не mount-вайте целия project и
не mount-вайте PostgreSQL data volume в operational контейнера. Архивът се
публикува единствено през изричния `/backups` mount и не остава в container
layer. `/tmp` остава tmpfs.

### Backup

PowerShell pattern след замяна на placeholder-ите:

```powershell
$BackupHostDir = "<BACKUP_HOST_DIR>"
$ActorUserId = "<ACTOR_USER_ID>"
docker compose run --rm --no-deps `
  -e BACKUP_ENCRYPTION_KEY `
  -v "${BackupHostDir}:/backups:rw" `
  app python scripts/backup_database.py `
  --output-dir /backups `
  --actor-user-id $ActorUserId
```

Linux shell pattern:

```bash
BACKUP_HOST_DIR="<BACKUP_HOST_DIR>"
ACTOR_USER_ID="<ACTOR_USER_ID>"
docker compose run --rm --no-deps \
  -e BACKUP_ENCRYPTION_KEY \
  -v "${BACKUP_HOST_DIR}:/backups:rw" \
  app python scripts/backup_database.py \
  --output-dir /backups \
  --actor-user-id "${ACTOR_USER_ID}"
```

Командата запазва PostgreSQL custom dump с `--no-owner` и `--no-acl`,
AES-256-GCM authenticated encryption, SHA-256 manifest и задължителен активен
audit actor. Отпечатват се само безопасното име на архива и неговият hash — не
се отпечатват `DATABASE_URL` или ключът. Ако се архивира отделно външно document
storage, mount-нете само неговия потвърден source каталог read-only на отделен
container path и подайте този path чрез `--documents-dir`.

### Verify

След създаването задайте `<BACKUP_FILE>` само като filename от защитения каталог.
Mount-ът е read-only, защото verify не записва нито в архива, нито в базата.

```powershell
$BackupHostDir = "<BACKUP_HOST_DIR>"
$BackupFile = "<BACKUP_FILE>"
docker compose run --rm --no-deps `
  -e BACKUP_ENCRYPTION_KEY `
  -v "${BackupHostDir}:/backups:ro" `
  app python scripts/verify_backup.py "/backups/$BackupFile"
```

```bash
BACKUP_HOST_DIR="<BACKUP_HOST_DIR>"
BACKUP_FILE="<BACKUP_FILE>"
docker compose run --rm --no-deps \
  -e BACKUP_ENCRYPTION_KEY \
  -v "${BACKUP_HOST_DIR}:/backups:ro" \
  app python scripts/verify_backup.py "/backups/${BACKUP_FILE}"
```

Verify извършва authenticated AES-GCM decrypt, валидира manifest формата и
сравнява checksum-а на database dump-а. Не променя базата.

### Destructive restore

Restore е изрично разрушителен. Преди изпълнение:

1. прегледайте exact target `DATABASE_URL`, без да го отпечатвате или поставяте
   в ticket/screenshot;
2. направете и verify-нете свеж вторичен backup;
3. спрете целия application write traffic;
4. verify-нете source архива чрез предходната команда;
5. потвърдете, че целевата DB е умишлено избраната;
6. обработете external document staging като отделна контролирана операция.

Source backup mount-ът остава read-only. Restore не е част от нормалния Compose
startup и никога не се изпълнява автоматично.

```powershell
$BackupHostDir = "<BACKUP_HOST_DIR>"
$BackupFile = "<BACKUP_FILE>"
$ActorUserId = "<ACTOR_USER_ID>"
docker compose run --rm --no-deps `
  -e BACKUP_ENCRYPTION_KEY `
  -v "${BackupHostDir}:/backups:ro" `
  app python scripts/restore_database.py "/backups/$BackupFile" `
  --confirm RESTORE_ASSETCORE `
  --actor-user-id $ActorUserId
```

```bash
BACKUP_HOST_DIR="<BACKUP_HOST_DIR>"
BACKUP_FILE="<BACKUP_FILE>"
ACTOR_USER_ID="<ACTOR_USER_ID>"
docker compose run --rm --no-deps \
  -e BACKUP_ENCRYPTION_KEY \
  -v "${BACKUP_HOST_DIR}:/backups:ro" \
  app python scripts/restore_database.py "/backups/${BACKUP_FILE}" \
  --confirm RESTORE_ASSETCORE \
  --actor-user-id "${ACTOR_USER_ID}"
```

Restore използва `pg_restore --clean --if-exists --exit-on-error` и изисква
точното `--confirm RESTORE_ASSETCORE`. Ако архивът съдържа external documents,
създайте отделен празен `<DOCUMENTS_STAGING_HOST_DIR>`, writable за UID 10001,
добавете само mount
`-v "<DOCUMENTS_STAGING_HOST_DIR>:/documents-staging:rw"` и аргумент
`--documents-staging /documents-staging`. Не използвайте backup каталога или
project tree като writable staging. Подмяната на реалното document storage е
последваща отделна контролирана операция.

`--actor-user-id` трябва да сочи активен реален оператор; успешният backup или
restore се записва в audit log без path, credentials или ключове.

## Host/venv алтернатива

При одобрен host-level operational достъп същите entry points могат да се
изпълнят от repository checkout с активна production конфигурация. Това е
алтернатива, а не containerized production процедурата по-горе:

```powershell
backend/.venv/Scripts/python.exe scripts/backup_database.py --output-dir <BACKUP_HOST_DIR> --actor-user-id <ACTOR_USER_ID>
backend/.venv/Scripts/python.exe scripts/verify_backup.py <BACKUP_HOST_DIR>\<BACKUP_FILE>
backend/.venv/Scripts/python.exe scripts/restore_database.py <BACKUP_HOST_DIR>\<BACKUP_FILE> --confirm RESTORE_ASSETCORE --actor-user-id <ACTOR_USER_ID>
```

За отделен проверим export и контрол на съхранените hashes използвайте:

```powershell
backend/.venv/Scripts/python.exe scripts/export_documents.py --output <EXPORT_FILE>
backend/.venv/Scripts/python.exe scripts/verify_document_hashes.py
```

## Реален PostgreSQL rehearsal

За автоматизиран реален round-trip задайте две различни PostgreSQL QA бази с
`test` или `qa` в имената им чрез `ASSETCORE_POSTGRES_SOURCE_URL` и
`ASSETCORE_POSTGRES_RESTORE_URL`, както и пътищата `PG_DUMP`/`PG_RESTORE`, после:

```powershell
backend/.venv/Scripts/python.exe scripts/postgres_smoke_test.py
```

Скриптът мигрира изолираната source база, създава криптиран dump, проверява го,
възстановява го с `--clean` в отделната restore база и сравнява Alembic head и
проверения 19-машинен регистър. Той отказва production-подобно име или еднакви
source/target URL-и и никога не отпечатва connection URL или ключ.
