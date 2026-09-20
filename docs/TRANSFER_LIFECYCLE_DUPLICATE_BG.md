# Разследване: жизнен цикъл и операции по предаване

## Доказателство преди промяната

База: `849b4c6253eba841ecf3cc6c80d7ddf07251de8b`. Чист checkout,
нов клон `assetcore-transfer-lifecycle-duplicate-fix`. Изолирана SQLite база,
мигрирана чрез нормалния runtime; осем добавени синтетични QA машини.
Използвани са реалните bulk HTTP endpoints, генериране на документи и двата
задължителни подписа за всяка операция. Production не е използвана.

| Сценарий | ISSUE batch / transfer ID | RETURN batch / transfer ID | API и UI преди промяната |
| --- | --- | --- | --- |
| QA A+B | 1 / 1,2 | 2 / 1,2 | Две карти, всяка total=2, returned=2, still issued=0 |
| QA C+D, връщане C | 3 / 3,4 | 4 / 3 | ISSUE 2/1/1 и допълнителна RETURN карта 1/1/0 |
| След връщане D | 3 / 3,4 | 5 / 4 | ISSUE 2/2/0 и две RETURN карти 1/1/0 |
| Независими QA E+F | 6 / 5,6 | 8 / 5,6 | Две карти 2/2/0 |
| Независими QA G+H | 7 / 7,8 | 9 / 7,8 | Две карти 2/2/0 |

Точни референции на първия пример: `HPWJ-B-20260919-000001` и
`RET-20260919195631-7EA299C8`. Подписващите official document ID са съответно
3 и 6; индивидуалните ISSUE документи са 1,2, RETURN документите са 4,5.
RETURN batch няма собствени `TransferProtocol.batch_id` връзки. Manifest-ът
съдържа `transfer_id=1,2` и `issue_batch_id=1` за всеки ред. Детайлите на двата
batch endpoint-а връщат същите transfer ID, но различни `operation`, signing
document ID и manifest hash. Потвърдените подписи остават отделни за ISSUE/RETURN.

Computer Use в локалния интерфейс потвърди девет карти за четири издавания.
Всяка видима референция съвпада с един от деветте DB/API batch записа.
Индивидуалната история съдържа осем transfer реда, без удвояване.
Това доказва дефекта в изолираната версия на кода; не представлява проверка на
конкретните production записи за машини 7/10 или 17/18.

## Авторитетна семантика (установена преди implementation)

1. `TransferBatch` е агрегат на операция, не непременно жизнен цикъл.
2. Bulk ISSUE създава batch, N transfer реда с FK към него, индивидуални
   official versions и DOCX/PDF, ISSUE manifest и отделен подписващ official act.
3. Всяко успешно bulk RETURN създава отделен batch и подписващ official act;
   обновява същите transfer редове и създава индивидуални RETURN версии/DOCX/PDF.
4. RETURN batch обвързва един чифт подписи с точния списък протоколи и hash.
5. Това е неизменяем операционен/подписващ агрегат; не е независимо издаване.
6. Точната връзка е `return_manifest.machines[].transfer_id` →
   `TransferProtocol.id` → `TransferProtocol.batch_id`. Manifest-ът пази и
   `issue_batch_id`/`issue_batch_reference`. Няма единствен parent FK, защото
   едно RETURN може да обхване няколко ISSUE партиди.
7. Връзката вече е записана и достатъчна; не са нужни евристики или нова колона.
8. Едно издаване може да има множество RETURN операции, включително анулирани
   опити. Ново издаване на същата машина има нови transfer ID и ISSUE batch ID.
9. Старият `GET /api/transfer-batches` връща всички операции. Единственият
   frontend потребител на списъка е `BulkTransfers`; той го рендерира директно.
10. „Партиди и напредък“ показва жизнения цикъл на първоначално издаване.
11. `_batch_progress` чете директните transfer FK за ISSUE и при липсата им
    използва RETURN manifest transfer ID. Така и двата агрегата отчитат едни и
    същи завършени връщания. `BatchSummaryOut` губи операцията, а картата няма
    различно представяне за нея. React key вече е правилният database ID.
12. RETURN batch е необходим за signing sessions, participants, signatures,
    проекции на подписи, document versions, manifest/hash, audit, cancellation,
    repair provenance и ZIP. Нито един от тези записи не трябва да се премахва.
13. Класификация: легитимни отделни операции + неподходяща API проекция за
    lifecycle екран + семантично неразличимо frontend представяне. Няма
    физически дублирани transfer редове или липсваща авторитетна връзка в QA.

## Решение

Адитивен `view=lifecycles` към списъка; default остава списъкът с операции.
Жизненият цикъл се идентифицира само от директния FK на transfer към ISSUE
batch. Детайлите показват свързаните RETURN операции чрез manifest transfer ID
и реалния FK. Подписващите състояния и целите за анулиране остават отделни.
Подреждането е стабилно по `created_at DESC, id DESC`.

При проверката на cancellation/retry се установи още една проява на същото
смесване: стар RETURN batch чете текущия `return_status` и всички RETURN файлове
по shared transfer ID, включително тези от нов опит. RETURN детайлите и прогресът
вече използват собствения `return_signing_status`, а файловете — точните
`official_document_id` от manifest. Lifecycle детайлите/ZIP показват публикуваните
версии; неподписаните отменени версии остават в историята, без да стават
достъпни като завършени протоколи. Legacy файлове без official record запазват
съществуващата си видимост. Това е read-only корекция, без промяна на съдържание.

NO MIGRATION. Без промени на документи, manifests, hashes, signatures, seed,
catalog, source registers или исторически бизнес записи.

## Одит на потребителите

| Повърхност | Класификация |
| --- | --- |
| Партиди и напредък | Засегната; използва lifecycle проекция |
| Batch Details | Добавя явен достъп до RETURN операции; точен обхват на документите при cancellation/retry |
| Индивидуална transfer история | Незасегната; един ред за transfer ID |
| Machine Passport / History | Незасегната; transfer и machine event идентичности |
| Machine Passport / Protocols | Умишлено пази отделните ISSUE/RETURN документи |
| Lifecycle timeline API и UI | Умишлено отделни issued/requested/returned събития по transfer ID |
| Official Documents registry | Незасегната; групира протоколите по точен transfer ID |
| ISSUE/RETURN протоколни изгледи | Умишлено отделни операции/документи |
| Генерирани ISSUE DOCX/PDF | Незасегнати; неизменяеми версии |
| Генерирани RETURN DOCX/PDF | Незасегнати; отделни неизменяеми версии |
| ZIP | Запазен достъп; RETURN обхватът е точният manifest, отменени неподписани опити не се публикуват |
| Reports/management | Незасегнати; не консумират batch списъка |
| Awaiting-signature | Разделени операции; точна цел за действие |
| Cancellation | Не трябва да анулира ISSUE при pending RETURN; проверява се отделно |
| QR → machine → transfer | Незасегната; авторитетна availability и active transfer |

## Валидация

Изпълнени локално с Python 3.12 и отделен PostgreSQL 16.15 на loopback:

| Команда | Резултат |
| --- | --- |
| `python -m pytest -q tests/test_bulk_transfers.py` | 24 passed |
| `python -m pytest -q tests/test_return_batch_signing.py` | 3 passed |
| `python -m pytest -q tests/test_transfer_workflow_v13.py` | 5 passed |
| `python -m pytest -q tests/test_integrated_transfer_signatures.py` | 5 passed |
| `python -m pytest -q tests/test_industrial_platform.py` | 16 passed |
| `python -m pytest -q tests/test_transfer_lifecycle_projection.py tests/test_transfer_workflow_v13.py tests/test_return_batch_signing.py tests/test_bulk_transfers.py` | 39 passed |
| `python -m pytest -q tests/postgres/test_transfer_lifecycle_projection_postgres.py --tb=short` | 7 passed, 41 warnings, 290.25 s |
| `python -u -m pytest -q -m 'not postgres' --durations=10 --tb=short --junitxml=.tmp/transfer-qa/backend-complete-results.xml` | 839 passed, 3 skipped, 21 deselected, 161 warnings, 2135.38 s |
| `pnpm typecheck` / `pnpm lint` / `pnpm build` (frontend) | PASS / PASS / PASS |
| `pnpm test` (frontend) | 480 passed, 44 files |
| `python -m compileall -q backend/app backend/alembic backend/scripts scripts tests` | PASS |
| `python -m ruff check backend/app backend/alembic backend/scripts scripts tests` | PASS |
| `python backend/scripts/validate_migration_history.py --require-all-protected` | PASS; 21 protected, no new revisions |
| `python backend/scripts/validate_authorization_inventory.py` | PASS; 170 routes, 80 mutating, 0 errors (включително 3 static routes с локалния build) |
| `python backend/scripts/catalog_v2_validation.py` (PYTHONPATH=backend) | PASS |
| `python backend/scripts/build_catalog_translations.py --check` (PYTHONPATH=backend) | PASS |
| `python -m pip check` | PASS |
| `python scripts/verify_release.py --output .tmp/transfer-qa/release` | PASS; 26/26 |
| `git diff --check` | PASS |

Новите седем backend случая се изпълняват със същите HTTP потоци и реално
подписване върху SQLite и мигрирани PostgreSQL схеми: пълно връщане, частични
1+1 и 2+1+1, независими партиди, повторно издаване, еднакви timestamps,
cross-issue RETURN, анулиране и повторен опит, pending ISSUE, legacy ISSUE без
manifest, права и невалиден view. Проверяват се DOCX/PDF/ZIP и fingerprints на
всички колони в 11 domain/history таблици преди и след read-only проекцията.
Шест frontend случая проверяват броя карти, прогреса, стабилната идентичност,
документите и точния RETURN ID за анулиране.

Dependency security gate е PASS за Python и frontend. Двата налични moderate
сигнала за Vitest/mocker са неблокиращи според съществуващата политика;
зависимостите не са променяни. Локалният Docker daemon не е стартиран;
контейнерните проверки се изпълняват в задължителния GitHub CI job.

Първоначалните незавършили пълни runs са повторени след прекъсването на сесията.
Един PostgreSQL опит е приключил със startup errors по време на възстановяване
на изолирания клъстер; повторението след готовност е горният успешен run.
Трите локални пропуска са два LibreOffice document-QA случая (липсва локален
LibreOffice) и един POSIX permissions случай под Windows. PostgreSQL случаите
са отделени от този run; CI ги изпълнява в собствен job.

## Computer Use след промяната

Свежа локална QA база с нормално генерирани и подписани документи първо показа
четири lifecycle карти за деветте операции от еквивалентния A–H сценарий.
После реалният браузър изпълни нови операции (избор на машини, преглед,
двама участници, ръчно нарисувани различни тестови подписи и потвърждение):

| UI сценарий | ISSUE | RETURN | Наблюдаван прогрес |
| --- | --- | --- | --- |
| I+J, пълно връщане | batch 10, `HPWJ-B-20260920-000010`, transfers 9,10 | batch 11, `RET-20260920055023-82F5FEA6` | Една карта: 0/2 → 2/2 |
| I+J, повторно издаване и първо частично връщане | batch 12, `HPWJ-B-20260920-000012`, transfers 11,12 | batch 13, `RET-20260920104003-E7311067`, transfer 11 | Отделен нов lifecycle: 0/2 → 1/2; предишният остава 2/2 |
| K+L, свеж пълен UI сценарий след успешния пълен test run | batch 14, `HPWJ-B-20260920-000014`, transfers 13,14 | batch 15, `RET-20260920104305-17C344D8` | Една карта: 0/2 → 2/2, still issued=0 |
| I+J, второ частично връщане | същият batch 12 | batch 16, `RET-20260920104606-721CC282`, transfer 12 | Същата карта: 1/2 → 2/2 |

K+L е създадено изцяло след завършването на автоматизираните проверки.
В неговите lifecycle детайли и отделния RETURN диалог се виждат ISSUE
`HPWJ-20260920-000013/000014` и RETURN `...000013-R/...000014-R`, с DOCX, PDF,
преглед и ZIP. Не се появява допълнителна RETURN lifecycle карта.
След второто частично връщане остават седем карти за седем издавания и
шестнадесет запазени операции. Независимите E+F и G+H остават отделни.

Наблюдаваните ID, референции, machine numbers, progress и RETURN parent връзки
са съпоставени с реалните GET endpoints чрез TestClient върху същата QA база
(без startup/seed и без промяна на бизнес данните). Използван е временен
QA bearer само в паметта. Readback-ът потвърждава lifecycle IDs
`14,12,10,7,6,3,1`; default operation списъкът остава пълен. QA базите,
скриптовете и JSON доказателствата са изключени от Git; няма синтетични
business записи в committed база или seed.

GitHub CI резултатите се записват в PR и окончателния отчет за точния head SHA.
