# CATALOG BUILDER 03D — окончателно приемане и hardening

## Обхват и начална версия

База `1bdb74b1c6d78d99ac4072690b66b5bf7b8d6be0` от актуалния `origin/main`.
Merge commits на 03A/03B/03C са проверени като предшественици. Работи се само в
development и собствени временни QA ресурси. Няма production достъп, merge или deployment.
Шестстъпковият процес, OCR алгоритъмът, DB схемата, миграциите, permissions и
историческите business данни не се променят.

**Работен статус: NOT READY — приемането още не е приключило.** Предходните зелени
CI резултати са база за сравнение, не заместител на новите 03D доказателства.
Началната матрица е в [QA inventory](qa/catalog-builder-03d/README.md).

## Независим audit и възпроизведени дефекти

1. **Parser capacity е локален за web процеса.** Нов regression стартира три
   независими Python процеса при лимит два. Преди поправката третият влиза в parser-а
   (`accepted` вместо `catalog_extraction_busy`). Добавени са nonblocking OS file
   leases в private runtime temp namespace, запазен е и thread semaphore.
   Лимитите не се увеличават, няма опашка без граница или нова инфраструктура.
   Lock файловете не се изтриват: unlink би позволил втори inode/двойно допускане.
   Unix worker наследява lease descriptor, за да го задържи при загуба на web parent.
   След прекратяване/изключение OS освобождава lock-а. Windows използва byte-range
   locks; съществуващият Job Object продължава да прекратява worker tree.
   Scope е един runtime/container с общ temp namespace; отделни реплики изискват
   собствен cgroup budget, не споделен cluster semaphore.
2. **Закъснял original preview след unmount губи Blob cleanup.** Нов frontend test
   първо FAIL с нула revoke calls; поправката освобождава URL от закъснелия отговор.
   Няма промяна на receipt, fingerprint, version, actor или review payload.
3. **Липсва single-page retry след прекъсване и refresh.** Edge 1/4 списъка преминаха;
   при 7 списъка прекъсната четвърта заявка запази 30 кандидата от останалите шест,
   но след refresh необработената страница нямаше retry. Нов component regression
   също FAIL преди поправката. Контекстното действие вече е налично за липсващ
   резултат при възобновена частично обработена група; RUNNING остава защитено.
4. **Повреден worker output не е контролиран отказ.** Три fault-injection случая
   преди поправката FAIL: невалиден JSON, JSON list и невалиден UTF-8.
   Границата вече изисква object и връща `catalog_extraction_resource_limit` / 422,
   без native exception текст, частично потвърждение или загуба на durable work.

Целеви локални резултати: 24 frontend PASS (39.59 s), 5 backend boundary PASS / 5
Windows platform SKIP (6.82 s); Ruff PASS. Пълният CI и реалното приемане са pending.

## Стратегия за доказване

- Реален D13: три Linux extraction повторения; отделен comparator след извличането.
  Original и expected не влизат в build context. OEM редове/страници/screenshots
  остават локални; разрешени са само hashes, counts, field accuracy и ресурси.
- Synthetic Edge: истински PDF, UI, API, stale tabs, source switch, review, touch
  markers, publication. Няма готови extraction/review резултати, записани в DB.
- N-page Edge: 1/4/7 списъка; прекъсната клиентска заявка по средата, refresh,
  запазени успешни страници и самостоятелен retry на липсващата.
- PostgreSQL: migration/constraints/concurrency плюс encrypted round trip с
  непразни пет durable таблици, човешка поправка, повторно извличане и source decision.
  Предишният all-table fingerprint comparator остава точен за всяка колона/ред;
  единствено новите законни backup/restore audit събития са извън историческата граница.
- Full CI: frontend, backend/SQLite, PostgreSQL и production-oriented Docker,
  authorization, PARTS-DOC, official DOCX/PDF, SBOM/dependency/release checks.

## Ресурсен бюджет и ограничения

Stress бюджетът е определен предварително в QA README: до 2 CPUs / 1 GiB / 64 PIDs,
192 MiB private tmpfs, максимум три клиенти и два допуснати worker-а. Worker остава
45 s / 1 GiB address-space, същите pixel/cell/word/output budgets.
Busy отговорът е непосредствен; queue wait е нула, няма обещана FIFO опашка.
Измервания с малка извадка не се представят като надежден production P95/SLA.

Начален паралелен локален build/browser/fault-test опит изчерпа свободния host RAM
резерв. Собствените допълнителни fault-test процеси бяха спрени; този опит е
INTERRUPTED, не PASS. Следващите тежки проверки се изпълняват последователно.

## OEM и hotspot ограничения

Разрешеният локален corpus включва D13, P200E, X25 и съществуващите verified
Falch/HYDWIN library PDFs. Наличност не означава доказана extractor точност.
Hammelmann original не е наличен в разрешения workspace; acceptance не се фабрикува.
D13 callout 48 срещу списъчна позиция 38 остава неразрешен OEM въпрос. Extraction
30/30 не означава verified hotspots; D13 не се публикува с измислени маркери.

## План за бъдещо внедряване — не е изпълняван

1. Независим review, разрешен merge и фиксиран release SHA; проверка на image/SBOM,
   подпис/хешове, migration head `20261009_0033` и текущата readiness матрица.
2. Отделно разрешение за production. Проверен encrypted backup с изолирано restore
   доказателство преди промяната; установяване на свободни RAM/disk и runtime budgets.
3. Контролирана смяна на image, без допълнителна 03D migration. Health/readiness,
   login/roles, 19 verified assets, shared catalogs, historic requests/signed DOCX/PDF,
   source inspection, native/OCR smoke и fail-closed publication checklist.
4. Прекратяване при нов integrity/hash drift, authorization failure, orphan worker,
   неправилен оригинален номер, загубено review, migration failure или unhealthy app.
5. Rollback с предходен image и запазена база: 03D не добавя schema. Запазват се
   0033 ledger, evidence, човешките решения и audit. Не се изпълнява lossy downgrade
   или изтриване/регенериране на исторически artifacts. Image преди 03A е несъвместим
   с новите publication правила и не е допустим rollback за нови публикации.
