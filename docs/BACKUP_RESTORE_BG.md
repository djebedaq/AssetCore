# Backup и restore

Архивът включва PostgreSQL custom dump, manifest и по избор външно document
storage. Всички генерирани документи/подписи, съхранени като DB bytes, влизат в
dump-а. Архивът се проверява с SHA-256 и се шифрова/удостоверява с AES-256-GCM.

Преди всяко production schema upgrade изпълнете backup, verify и поне
периодичен restore rehearsal в отделна база. Едва след успешната проверка
изпълнете one-shot `python -m app.runtime prepare`. Не приемайте успешен
`/api/health` за доказателство за backup или актуална schema; използвайте
`/api/ready` и отделния backup manifest.

Задайте `DATABASE_URL` и отделен случаен 32-byte Base64
`BACKUP_ENCRYPTION_KEY`, след което:

```powershell
backend/.venv/Scripts/python.exe scripts/backup_database.py --output-dir C:\AssetCoreBackups --actor-user-id <ID>
```

Не съхранявайте ключа до архива. Проверявайте restore периодично в отделна
PostgreSQL инстанция:

```powershell
backend/.venv/Scripts/python.exe scripts/verify_backup.py C:\AssetCoreBackups\assetcore-....acbackup
backend/.venv/Scripts/python.exe scripts/restore_database.py C:\AssetCoreBackups\assetcore-....acbackup --confirm RESTORE_ASSETCORE --actor-user-id <ID>
```

Restore използва `pg_restore --clean --if-exists` и е разрушителен за посочената
целева база. Потвърдете точния URL, направете втори архив и спрете пишещия трафик.
Външните файлове се извличат само в празна staging папка чрез
`--documents-staging`; подмяната им е отделна контролирана операция.

`--actor-user-id` трябва да сочи активен реален оператор; успешната операция се
записва в audit log без path, credentials или ключове. За отделен проверим export
и контрол на съхранените hashes използвайте:

```powershell
backend/.venv/Scripts/python.exe scripts/export_documents.py --output C:\AssetCoreExports\documents.zip
backend/.venv/Scripts/python.exe scripts/verify_document_hashes.py
```

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

Production Compose web контейнерът е с read-only root filesystem. За ръчен
backup стартирайте отделен one-shot контейнер с изрично writable mount към
защитения backup каталог; не правете `/app` writable и не съхранявайте архива
или ключа във filesystem-а на web контейнера. PostgreSQL не е публикуван към
host по подразбиране; административният достъп трябва да е през защитена
вътрешна мрежа или краткотраен loopback-only development override.
