# Backup и restore

Архивът включва PostgreSQL custom dump, manifest и по избор външно document
storage. Всички генерирани документи/подписи, съхранени като DB bytes, влизат в
dump-а. Архивът се проверява с SHA-256 и се шифрова/удостоверява с AES-256-GCM.

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
