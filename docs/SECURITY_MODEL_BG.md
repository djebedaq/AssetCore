# Модел за сигурност

- Password hashes са PBKDF2-SHA256 със случаен salt; временната bootstrap парола
  се сменя при първи вход и никога не се връща от API.
- Bearer token включва expiry и user token version; деактивация, роля, password и
  owner transfer обезсилват старите сесии.
- Permission матрицата е централизирана, а собственикът не разширява ролите.
- Важните операции се валидират server-side и се одитират без secrets.
- Active transfer е authoritative; partial unique index и PostgreSQL row locking
  предотвратяват двойно издаване. SQLite използва process lock и същия index.
- License signature е Ed25519; private key не се разполага в приложението.
- Signature strokes/PNG са AES/Fernet encrypted at rest и са обвързани с hashes.
- Signed versions, snapshots, source documents и audit history не се редактират
  през нормалните workflows; корекциите добавят нова версия.
- `.env`, DB, dumps, backups, private keys и generated exports са игнорирани от Git.
- Аварийната административна процедура е owner-only, изисква повторна парола и
  основание, изтича до 60 минути, показва глобално известие и не повишава права.
  Няма recovery/master парола; полето за MFA е подготовка, не активна MFA защита.

Организацията трябва допълнително да осигури TLS, managed PostgreSQL encryption,
secret rotation, least-privilege database user, мрежови правила, off-site backups,
централизирани logs и формална incident-response процедура.
