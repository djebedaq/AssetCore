# Security доказателства

`python-audit.json` е резултат от реалния repository audit script след pypdf 6.21.2. Политиката блокира HIGH/CRITICAL/UNKNOWN и допуска само точни валидни изключения; не са добавяни изключения. Информационните findings за инструмента pip остават видими.

Backend tests: reader/manager permissions, authenticated original images, immutable native provenance, reserved marker rejection в scalar/table/label, protected slot placement, missing source rollback, native KK signer отказ преди session mutation. Съществуващите security/authorization/signing/session и PostgreSQL suites се изпълняват в CI.

Private references не се включват. Публичните QA стойности са маркирани синтетични. Стари audit/document rows не се редактират или изтриват. Новият manifest не съдържа credentials или filesystem references.
