# AssetCore — доклад за реализацията

## Начално състояние
Анализирана е предоставената версия `AssetCore-main 5(1).zip`. Системата вече съдържа развита архитектура за трансфери, подписи, документи, ремонти, техническа библиотека и каталог на части.

## Реално извършени промени
1. Външният получател при издаване вече се валидира само с три имена. Полетата за длъжност и фирма/отдел са премахнати от потребителския интерфейс и са optional в API/модела.
2. Добавена е Alembic миграция `20260805_0007_external_signer_optional_fields.py`, съвместима с PostgreSQL и SQLite.
3. При приемане името на връщащия се зарежда от активното издаване и не се въвежда повторно от потребителя.
4. Backend-ът не приема свободна подмяна на връщащия. Създава подписващия участник от запазеното име в активния transfer snapshot.
5. Добавена е проверка, че в една операция по приемане могат да участват само машини, издадени на един и същ човек.
6. Основните български действия са променени от „Групово издаване/връщане“ на „Издай/Приеми“.
7. При приключване на ремонт документът се генерира принудително с публикувания български шаблон, независимо от езика на профила.

## Променени файлове
- `backend/app/models.py`
- `backend/app/schemas.py`
- `backend/app/transfer_service.py`
- `backend/app/industrial_api.py`
- `backend/alembic/versions/20260805_0007_external_signer_optional_fields.py`
- `frontend/src/BulkTransfers.tsx`
- `frontend/src/i18n.tsx`

## Проверки
- `python -m compileall -q backend/app` — успешно.
- `python -m pytest -q` — стартира, но не завърши в наличния лимит за изпълнение.
- `python -m pytest -q tests/test_bulk_transfers.py -x` — стартира и премина първите 6 теста, но не завърши в наличния лимит.
- Frontend dependency install/typecheck — не е изпълнен докрай, защото средата няма мрежов достъп до `registry.npmjs.org` (`EAI_AGAIN`).
- Docker/PostgreSQL full-stack проверка — не е изпълнена в тази среда.

## Ограничения
Тази редакция реализира критичните корекции по издаване, приемане и ремонтния език. Пълният импорт и ръчна верификация на всички части от трите големи ръководства, pixel-perfect DOCX/PDF шаблонът по снимките, condition checklist моделът и пълният batch-signature refactor не са завършени в тази версия. Те не са представени като готови.

## Оценка
Версията е **готова за локални разработващи тестове след изпълнение на миграцията**, но не е готова за production без пълно изпълнение на тестовете, document QA и frontend build.


## Допълнение 2 — състояние и комплектност
Добавен е структуриран checklist за 10-те реда от оригиналния протокол. Всеки ред поддържа състояние, кратка забележка и дължина в метри за захранващ шланг, ВН шланг и кабел. Началният и върнатият checklist се пазят отделно в `transfer_protocols`, включват се в API payload-а и се визуализират в DOCX/PDF таблицата. Добавена е миграция `20260805_0008_transfer_checklists.py` и schema тестове.

## Проверки на допълнението
- `python -m compileall -q backend/app` — успешно.
- `python -m pytest -q tests/test_transfer_checklist_schema.py` — 2 теста успешно.
- Frontend typecheck е стартиран, но средата няма инсталирани npm dependencies (`react`, `vite`, typings и др.), затова резултатът не може да се използва като проверка на редакцията. Няма твърдение за успешен frontend build.

## Допълнение v3 — безопасно анулиране на незавършени операции

Добавен е транзакционен endpoint `POST /api/transfer-batches/{batch_id}/cancel`, достъпен за администратор. Той допуска анулиране само когато има издаване или приемане в статус `AWAITING_SIGNATURE`.

При анулиране:
- неизползваните signing sessions се маркират като отказани;
- незавършените версии на официалните документи стават `CANCELLED`;
- при незавършено издаване машината остава налична и transfer-ът не става активен;
- при незавършено приемане първоначалното активно издаване се запазва;
- причината, потребителят и timestamp-ът се записват към batch-а;
- създава се audit запис;
- повторно анулиране е idempotent и не създава дублирани промени.

Добавена е миграция `20260805_0009_safe_transfer_cancellation.py` за PostgreSQL и SQLite чрез batch alter.

Проверки: `python -m compileall -q backend/app` — успешно; целеви schema тестове — 4 passed.

## Допълнение v4 — един подписващ акт за издаване на няколко машини

Реализирано е истинско batch подписване за операцията **„Издай“**:

- за целия batch се създава един immutable signing manifest;
- manifest-ът съдържа точния batch ID, batch reference, получателя, точния списък от машини, transfer IDs, протоколни номера, official document IDs, version IDs и signing SHA-256 за всеки протокол;
- предаващият подписва веднъж и получателят подписва веднъж, независимо от броя машини;
- екранът за подпис показва всички машини от операцията и batch manifest SHA-256;
- двата оригинални подписа са обвързани с общия signing document и manifest hash;
- във всеки отделен машинен протокол се създава проследима `BATCH_PROJECTION`, свързана с оригиналния подпис чрез `source_signature_id` и `batch_manifest_sha256`;
- machine status не се променя преди двата подписа;
- след втория подпис всички протоколи и всички машини в batch-а се финализират транзакционно;
- повторно използване на произволен стар подпис остава забранено; повторното визуализиране в документите е допустимо само като вътрешна projection от същия signing act;
- анулирането на незавършено издаване обезсилва и общия batch signing document.

Добавена е Alembic миграция `20260805_0010_issue_batch_signing.py`. Освен новите batch signing полета тя заменя глобалния unique индекс върху signature image SHA-256 с partial unique индекс само за оригинални подписи. Така projection записите от един и същ signing act са проследими, без да се разрешава повторна употреба на подпис в друга операция.

Поправени са и миграциите `20260805_0008` и `20260805_0009`, така че да са idempotent при празна база, тъй като първата историческа миграция създава текущата metadata схема преди последващите миграции.

### Проверки за v4

- `python -m compileall -q backend/app` — успешно.
- `pytest -q tests/test_issue_batch_signing.py` — 1 passed.
- `pytest -q tests/test_issue_batch_signing.py tests/test_transfer_cancellation_schema.py tests/test_bulk_transfers.py::test_bulk_issue_is_atomic_when_all_machines_are_available` — 4 passed.
- `alembic upgrade head` върху нова SQLite база — успешно до `20260805_0010`.
- Актуализирани са старите integrated signature тестове към новия batch contract. Целевият комплект от 6 теста за batch signing, защита срещу повторна употреба, cancellation schema и атомарно издаване премина успешно.

### Текуща оценка след v4

Batch подписването за **издаване** е реализирано и покрито с целеви integration тест. Batch подписването за **приемане/връщане** все още използва отделни signing задачи за всеки документ и остава за следващата редакция.

## Допълнение v5 — един подписващ акт за приемане на няколко машини

Реализирано е истинско batch подписване за операцията **„Приеми“**:

- при избор на една или няколко машини се създава отделен return operation batch с immutable manifest;
- manifest-ът съдържа точните transfer IDs, machine IDs, номерата на машините, първоначалните issue batch-и, номерата на протоколите, official document/version IDs, signing SHA-256, следващ статус и местоположение;
- машините могат да са от различни първоначални batch-и, когато immutable получателят е един и същ;
- връщащият подписва веднъж и приемащият подписва веднъж за целия списък;
- екранът за подпис показва всички избрани машини, return batch reference и manifest SHA-256;
- във всеки отделен return протокол се създават две `BATCH_PROJECTION` подписи, свързани с оригиналните подписи чрез `source_signature_id` и `batch_manifest_sha256`;
- машините остават `ISSUED`, а активните издавания остават валидни, докато не бъдат потвърдени и двата подписа;
- след втория подпис всички return протоколи се финализират и всички избрани машини преминават към зададения следващ статус в една транзакция;
- оригиналните issue batch-и се актуализират поотделно, включително при mixed-batch приемане;
- return operation batch-ът има собствен екран за детайли и ZIP на финалните протоколи;
- безопасното анулиране обезсилва return signing sessions и signing document-а, но запазва първоначалните активни издавания.

Добавена е Alembic миграция `20260805_0011_return_batch_signing.py` за PostgreSQL и SQLite.

### Проверки за v5

- `python -m compileall -q backend/app` — успешно.
- `pytest -q tests/test_return_batch_signing.py::test_return_batch_uses_two_signatures_across_different_issue_batches` — 1 passed.
- `pytest -q tests/test_return_batch_signing.py::test_pending_return_batch_can_be_cancelled_without_closing_issue` — 1 passed.
- `pytest -q tests/test_return_batch_signing.py::test_return_batch_rejects_machines_issued_to_different_people` — 1 passed.
- `pytest -q tests/test_issue_batch_signing.py` — 1 passed.
- `pytest -q tests/test_integrated_transfer_signatures.py::test_return_remains_pending_until_return_and_acceptance_signatures` — 1 passed.
- `pytest -q tests/test_bulk_transfers.py::test_full_batch_return_closes_every_individual_transfer` — 1 passed.
- `pytest -q tests/test_bulk_transfers.py::test_partial_batch_return_keeps_remaining_machine_issued` — 1 passed.
- `pytest -q tests/test_bulk_transfers.py::test_mixed_batch_return_updates_each_batch_and_scopes_its_audit` — 1 passed.
- `pytest -q tests/test_bulk_transfers.py::test_return_without_active_issue_and_double_return_are_rejected` — 1 passed.
- `alembic upgrade head` върху нова SQLite база — успешно до `20260805_0011`.

### Текуща оценка след v5

Batch подписването с един подпис на човек е реализирано и за **„Издай“**, и за **„Приеми“**. Остават преработването на протокола по оригиналния образец, директното позициониране на подписите в основната A4 страница, пълният каталог от ръководствата, визуалният каталог, ръчната заявка за непозната част, UI за анулиране, окончателният ремонтен QA и пълните frontend/Docker/PostgreSQL проверки.

## Допълнение v6 — оригинален едностраничен протокол и подписи в основните полета

Преработени са официалните шаблони за издаване и приемане по предоставените снимки на реалния протокол.

Реализирано е:

- нови публикувани DOCX шаблони `transfer_issue-*-v3.docx` и `transfer_return-*-v3.docx` за BG/EN/RU;
- фирмена шапка с KRZ, ODESSOS SHIPREPAIR & CONVERSION и RINA/AQAP 2110;
- оригиналната последователност на полетата за дата, оборудване, модел, заводски номер и сериен номер;
- точните 10 реда за комплектност и състояние;
- предназначение/място на използване и забележки;
- двуредова подписна таблица по образеца;
- външният участник се показва само с трите си имена и ролята в операцията, без изискване за длъжност, фирма, цех или отдел;
- вътрешният участник се показва с трите имена, операцията и потвърдената длъжност;
- графичните подписи се вграждат директно в двете оригинални подписни клетки;
- премахнато е добавянето на отделна страница „Потвърдени подписи“ за transfer протоколите;
- DOCX и PDF се финализират от един и същ попълнен DOCX snapshot;
- при недостъпна LibreOffice конверсия PDF fallback-ът поставя подписите върху първата страница вместо да добавя annex;
- template seed-ът публикува версия 3 и автоматично сваля от публикация по-старите версии за същия език;
- добавен е възпроизводим генератор `scripts/generate_transfer_templates.py`;
- разширен е `backend/scripts/document_qa.py` с едностранична проверка, контрол на трите header изображения и проверка на оригиналните checklist редове.

### Реални проверки за v6

- `python -m compileall -q backend/app backend/scripts scripts/generate_transfer_templates.py tests/test_original_protocol_layout.py` — успешно.
- `pytest -q tests/test_original_protocol_layout.py` — **8 passed**.
- `pytest -q tests/test_issue_batch_signing.py::test_issue_batch_uses_one_two_signature_act_for_three_machines` — **1 passed**.
- `pytest -q tests/test_return_batch_signing.py::test_return_batch_uses_two_signatures_across_different_issue_batches` — **1 passed**.
- Двата целеви integrated теста за издаване и приемане след всички подписи — **2 passed**.
- `pytest -q tests/test_industrial_platform.py::test_template_version_upload_is_draft_until_human_publish` — **1 passed**.
- `backend/scripts/document_qa.py` — успешно; всички release checks са `true`.
- QA PDF за издаване — 1 страница, визуално проверен.
- QA PDF за приемане — 1 страница, визуално проверен.
- Подписан примерен DOCX/PDF — 1 страница, два графични подписа в оригиналните клетки, без annex страница.

### Текуща оценка след v6

Протоколите за „Издай“ и „Приеми“ вече следват реалния образец и подписите се поставят в основната A4 страница. Остават каталогът за трите производителя, визуалният избор на части, ръчната заявка за неизвестна част, frontend диалогът за анулиране, окончателният ремонтен QA и пълните frontend/Docker/PostgreSQL проверки.

## Допълнение v7 — проверен каталог за CombiJet, Falch и HYDWIN/Fussen

Изграден е контролиран каталог от приложените официални ръководства и part lists. Данните не се създават от свободен OCR резултат и не се допълват с измислени Part No., позиции или съвместимости. Всеки запис е свързан с оригиналния файл, страницата и SHA-256 на източника.

### Реализирано

- Добавен е immutable каталог manifest: `backend/resources/catalog/verified_parts_v1.json`.
- Добавен е проверим importer `backend/app/catalog_import.py`, който при seed:
  - проверява наличието и SHA-256 на всеки официален източник;
  - отказва импорт при променен или липсващ ръководен файл;
  - upsert-ва записите по производител, модел, възел, позиция и Part No.;
  - не изтрива потребителски добавени каталожни записи;
  - маркира внесените записи като `VERIFIED_SOURCE_TABLE`.
- Каталожните количества вече поддържат дробни стойности. Това запазва Falch количества като `0.35`, без неправилно закръгляне до цяло число.
- Добавени са полета за:
  - exploded-view/figure описание;
  - diagram page;
  - версия на ръководството;
  - SHA-256 на source документа;
  - verification status;
  - официален `replaced by` Part No.
- Добавена е Alembic миграция `20260805_0012_verified_part_catalog.py`, проверена върху:
  - празна SQLite база;
  - база, мигрирана предварително с v6 до `20260805_0011`.
- Техническата библиотека вече свързва документите с точния модел и съвместимите инвентарни номера.
- `/api/catalog/parts` поддържа филтри по:
  - машина;
  - производител/марка;
  - модел;
  - възел;
  - позиция;
  - verification status;
  - общо търсене.
- Каталогът във frontend зарежда само съвместимите части, когато е отворен от конкретна машина, и добавя филтър по възел.
- Visual source viewer започва от exploded-view страницата (`diagram_page`), когато тя е надеждно потвърдена.
- Добавен е автоматичен import/validation report:
  - `docs/PART_CATALOG_IMPORT_VALIDATION_BG.md`;
  - `docs/PART_CATALOG_IMPORT_VALIDATION.json`;
  - `backend/scripts/catalog_validation.py`.

### Потвърдени каталожни позиции

- **CombiJet JE60-500:** 262 позиции.
- **Falch Wheel Jet 15-e / 500 bar:** 266 позиции.
- **Falch Wheel Jet 30-e / 1000 bar:** 229 позиции.
- **HYDWIN/Fussen FCE15/50:** 17 позиции.
- **Общо:** 774 потвърдени позиции.

### Контролирано непотвърдени/изключени данни

- Falch офертата `offer_sq-de103869_2025-10-22.pdf` остава в техническата библиотека, но не е смесена с exploded-view каталога, защото е търговска оферта без позиционна схема.
- HYDWIN изображението с позиции 1–8 няма приложена надеждна таблица за връзка позиция → Part No.; не са създадени измислени hotspot координати.
- CombiJet позиция 55 „PUMP SUPPORTS“ е с Part No. `*` и не е внесена като официална каталожна част.
- Hotspot координати не са генерирани автоматично. Изборът по потвърдена позиция от таблицата остава източникът на истина до ръчна координатна проверка.

### Реални проверки за v7

- `python -m compileall -q backend/app backend/scripts scripts tests` — успешно.
- `pytest -q tests/test_verified_part_catalog.py` — **3 passed**.
- `alembic upgrade head` върху празна SQLite база — успешно до `20260805_0012`.
- Upgrade на база, създадена от v6 до `20260805_0011`, след това към v7 — успешно; `quantity` е мигрирано към FLOAT и новите provenance колони са налични.
- `backend/scripts/catalog_validation.py` — успешно, 774 валидни записи, 0 грешки.
- `pytest -q tests/test_verified_part_catalog.py tests/test_migrations.py` — **7 passed**; проверени са upgrade/downgrade миграциите и неприкосновеността на регистъра.
- `scripts/verify_release.py` — **21/21 проверки успешни**, включително Alembic head, 19 машини, точно 4 роли, owner designation, 12 публикувани шаблона, 774 проверени каталожни позиции, health и document hash QA.
- Frontend dependency install — неизпълнен поради външна DNS/registry грешка `EAI_AGAIN registry.npmjs.org`; frontend production build не е заявен като успешен.

### Текуща оценка след v7

Пълният проверен каталог за трите производителя е внесен с проследимост към източник, страница, фигура/diagram page, версия и SHA-256. Не са създавани непотвърдени hotspots. Release verifier-ът е успешен. Остават завършване на визуалния каталог с надеждни ръчно проверени hotspots там, където е възможно, ръчната заявка за неизвестна част, frontend диалогът за анулиране, окончателният ремонтен QA и пълните frontend/Docker/PostgreSQL проверки.

## Допълнение v8 — machine-first визуален каталог с реално PDF page rendering

Завършен е следващият етап на визуалния каталог. Работният поток вече започва от конкретна машина от проверения регистър и не показва несъвместими части или ръководства.

### Реализирано

- Добавен е задължителен избор на конкретна машина преди отваряне на визуалния каталог.
- След избора системата зарежда само потвърдените каталожни записи, чиито `compatible_machine_numbers` съдържат избраната машина.
- Възлите се извеждат автоматично от съвместимите части за избрания модел.
- За избран възел се показват:
  - официалният технически документ;
  - exploded-view страницата, когато има потвърден `diagram_page`;
  - официалната таблица, когато няма надеждна връзка към exploded-view;
  - списъкът с позиции, Part No., описание, количество и source page.
- Изборът на позиция работи както от потвърден hotspot, така и от таблицата.
- Когато няма потвърдени координати, системата не симулира hotspot. Избраната позиция се маркира в таблицата и с видим selected-position индикатор.
- В основния визуален каталог се показват само `is_verified=true` hotspots.
- Добавени са zoom до 250%, reset, fullscreen и pan с мишка, touch и stylus чрез Pointer Events.
- Избраният каталожен запис показва Part No., описание, количество, съвместимост, source page и verification status.
- „Добави към заявка“ отваря съществуващия проследим request workflow с предварително избрана машина и възможност за количество.
- Администраторският hotspot editor остава отделен и вече използва същото точно page-rendering изображение, така че координатите да съвпадат с визуализираната PDF страница.

### Backend PDF preview

Добавен е защитен endpoint:

`GET /api/technical-library/{document_id}/pages/{page_number}/preview`

Той:

- чете само контролирани технически документи от библиотеката;
- визуализира конкретна PDF страница като PNG чрез PyMuPDF;
- валидира page range;
- ограничава scale и максималния брой пиксели;
- връща SHA-256 на source документа, page count, ETag и private cache headers;
- не разкрива абсолютни файлови пътища;
- връща локализиран structured error при не-PDF документ или липсваща страница.

Техническата библиотека вече връща контролирания относителен `source_key` и page preview endpoint template. Това позволява надеждно свързване на каталожния `source_document` с точния документ без догадки по име.

### Променени файлове за v8

- `backend/app/industrial_api.py`
- `backend/requirements.txt`
- `frontend/src/IndustrialPlatform.tsx`
- `frontend/src/i18n.tsx`
- `frontend/src/styles.css`
- `frontend/src/types.ts`
- `tests/test_verified_part_catalog.py`

Няма нова database миграция, защото v8 използва съществуващите `diagram_page`, `source_document`, `PartHotspot` и `TechnicalDocument` модели.

### Реални проверки за v8

- `python -m compileall -q backend/app backend/scripts scripts tests` — успешно.
- `pytest -q tests/test_verified_part_catalog.py` — **5 passed**.
- `pytest -q tests/test_verified_part_catalog.py tests/test_i18n_roles_seed.py` — **11 passed**.
- `pytest -q tests/test_industrial_platform.py::test_visual_part_hotspot_requires_provenance_and_human_verification` — **1 passed**.
- TypeScript syntax transpilation чрез наличния глобален TypeScript compiler за `IndustrialPlatform.tsx`, `i18n.tsx` и `types.ts` — без syntax diagnostics.
- Реална preview проверка на `CombiJet JE60-500`, PDF страница 28 — PNG signature, source SHA-256, page count и ETag са потвърдени от integration тест.
- Frontend dependency install/build не е изпълнен, защото `registry.npmjs.org` върна `EAI_AGAIN`; не се заявява успешен production build.

### Текуща оценка след v8

Machine-first визуалният каталог, изборът по възел/позиция, fallback таблицата, PDF page preview, zoom/pan и използването само на потвърдени hotspots са реализирани. Остават точният workflow за „Част без потвърден part number“, frontend диалогът за безопасно анулиране, окончателният QA на ремонтния протокол и пълните frontend/Docker/PostgreSQL проверки.

### Допълнителна release проверка за v8

- `python backend/scripts/catalog_validation.py` — валиден manifest, **774** записа и **0** грешки.
- `python verify_release.py` — **21/21 проверки успешни**, включително Alembic head, точно 19 машини, точно 4 роли, owner designation, 12 публикувани шаблона, 774 проверени каталожни позиции, health и document/hash QA.


## 26. V9 — заявка за част без потвърден Part No.

- Добавен е отделен workflow за заявка на непозната част с конкретна машина, възел, описание, снимка, количество и забележка.
- Редът се маркира структурирано с `is_unknown_part=true` и видимо като „Част без потвърден part number“.
- Не се създава автоматично запис в официалния каталог и не се попълва фиктивен part number.
- Снимката се съхранява като защитено приложение, свързано с конкретния ред на заявката.
- Само администратор може по-късно да свърже реда с активна, потвърдена и съвместима каталожна част. Оригиналното описание и снимка се запазват.
- Добавена е миграция `20260805_0013_unknown_part_requests.py` за PostgreSQL и SQLite.
- Добавени са BG/EN/RU преводи, UI за създаване и административно свързване и тестове за липса на автоматичен catalog insert.

### V9 проверки

Изпълнени реално:

- `python -m compileall -q backend/app` — успешно.
- `pytest -q tests/test_unknown_part_requests.py` — **4 passed**.
- Регресионен пакет за заявки, каталог, i18n и миграции — **15 passed**.
- `python backend/scripts/catalog_validation.py` — **774 валидни позиции, 0 грешки**.
- `python scripts/verify_release.py` — **21/21 проверки успешни**.
- TypeScript transpile/syntax проверка на променените frontend файлове — успешно.
- Пълният `PYTHONPATH=.:backend pytest -q` беше стартиран, но не завърши в наличния времеви лимит.
- Пълният frontend dependency install/build не е изпълнен поради липсващи `node_modules` и недостъпен npm registry в средата.


## 27. V10 — безопасно анулиране в потребителския интерфейс

- Добавен е видим бутон „Анулирай операцията“ само за batch операции с `awaiting_signature_machines > 0`.
- Бутонът е достъпен само за потребители с право `transfers.create`, съответстващо на защитата на backend endpoint-а.
- Диалогът изисква причина от минимум 3 знака, блокира двойно изпращане и показва различния ефект при ISSUE и RETURN.
- При ISSUE машините се освобождават за ново издаване; при RETURN първоначалното активно издаване остава валидно.
- След успех се показват `cancelled_transfers` и `invalidated_signing_sessions`, а наличността, batch списъкът и детайлите се презареждат.
- Добавена е локализация на `batch_not_pending`, `batch_not_found` и permission errors.
- Backend schema trim-ва причината и отказва стойност, съдържаща само интервали.
- Коригирани са останали видими текстове „групово“ в основните действия и confirmation заглавието.

### V10 проверки

- Python compile check на backend/tests — успешно.
- Targeted backend cancellation tests — успешно.
- TypeScript syntax transpilation на променените файлове — успешно.
- Изолиран TypeScript semantic check със stub declarations за локалните модули — успешно.
- Пълният frontend install/build не е изпълнен: вътрешният npm registry върна 404 за `@eslint/js` и `@types/react`.

## 28. V11 — окончателен вътрешен ремонтен протокол

### Реализация

- Ремонтите са вътрешен workflow без външно предаване, приемане или външни подписи.
- Добавен е модел `repair_participants` с immutable snapshots на три имена, длъжност и принос.
- Отговорният механик се записва с три имена и длъжност; приключването не подменя вече определения отговорник.
- Добавени са API операции за добавяне и премахване на участници преди приключване. След статус `COMPLETED` ремонтът и участниците са заключени.
- Ремонтният протокол се генерира само на български, независимо от BG/EN/RU интерфейса или подаден query параметър.
- Протоколът съдържа машина, проблем, състояние преди, диагностика, извършена работа, използвани части, тестов резултат, състояние след, допълнителни участници, статус, дата, изпълнител и длъжност.
- DOCX и PDF използват един immutable snapshot. Примерните документи са едностранични и са проверени чрез PNG render.
- При липсващ или невалиден BG шаблон приключването не се rollback-ва: ремонтът и машинният статус се запазват, а API връща `document_generation_warning` с точна административна причина.
- Повторно `COMPLETED` е idempotent и не генерира дублиран протокол.
- Добавени са BG/EN/RU интерфейсни текстове, без блокиращ избор на език.

### Миграция

- `20260805_0014_internal_repair_protocol.py`
- Проверени са upgrade от празна SQLite база, downgrade до `0013` и повторен upgrade до `0014`.

### Реални проверки

- `python -m compileall -q backend/app backend/scripts` — успешно.
- `pytest -q tests/test_internal_repair_protocol_v11.py` — **4 passed**.
- Регресионни repair/template тестове — **6 passed**, 21 deselected.
- Release packaging тестове — **2 passed**.
- Изолиран TypeScript semantic check на променения repair UI — успешно.
- Release verifier — **21/21 проверки успешни**.
- DOCX render — 1 страница, без clipping/overlap.
- PDF render — 1 страница, без clipping/overlap.
- Пълният backend `pytest -q` беше стартиран, но не завърши в наличния 180-секунден лимит; не се представя като успешно преминал.

### Текуща оценка след V11

Функционалните промени от промпта са реализирани, включително ремонтния протокол. Остават инфраструктурните финални проверки: реален frontend dependency install/typecheck/lint/tests/build, Docker Compose и PostgreSQL full-stack workflow, след което окончателно release почистване и staging оценка.

## 29. V12 — финален release етап

### Реализация

- Версията е актуализирана до `1.3.0-rc.2`.
- Поправен е PostgreSQL smoke test, който е сравнявал restore базата с остарял Alembic revision. Очакваният revision вече се извлича динамично от текущия Alembic head.
- Добавени са самостоятелни GitHub Actions jobs за frontend, backend, PostgreSQL и Docker.
- PostgreSQL job изпълнява миграции, seed, криптиран backup, проверка и restore в отделна тестова база.
- Docker job валидира Compose конфигурацията и изгражда production image.
- Добавени са infrastructure contract тестове.
- Коригиран е regression тестът за техническите документи в машинния паспорт, така че да отчита вече внесената проверена техническа библиотека.

### Реални резултати

- `python -m compileall` — успешно.
- Pytest collection — **132 теста**.
- Всички **132 теста са изпълнени успешно** в контролирани групи. Една обща pytest сесия надвишава максималния runtime на shell инструмента, затова не се представя като единична завършена команда.
- `scripts/verify_release.py` — **21/21 PASS**.
- Document QA — всички release checks са `true`.
- TypeScript syntax/transpile — **24 файла успешно**.
- Изолирана semantic TypeScript проверка — успешно.
- Compose, workflow и Dockerfile static validation — успешно.

### Ограничения на средата

- `pnpm` не може да бъде изтеглен поради `EAI_AGAIN registry.npmjs.org`.
- Вътрешният npm registry връща HTTP 404 за необходимите frontend пакети.
- `docker`, `psql`, `postgres`, `pg_dump` и `pg_restore` не са налични.
- Ruff не е наличен в локалната среда и не може да бъде изтеглен от достъпния Python package mirror.
- Тези проверки не са отбелязани като локално успешни; те са конфигурирани като CI gates.

### Финална оценка

- Branch: N/A — архивен workflow поради GitHub integration 403.
- Commit SHA: N/A — ще бъде създаден при качването от собственика.
- Pull Request: N/A — ще бъде отворен от собственика.
- Merge commit: N/A — merge се извършва от собственика.
- Статус: **готова за staging като release candidate след зелени frontend, backend, PostgreSQL и Docker CI jobs**.
- Production: **не се декларира преди реален staging smoke test, backup/restore rehearsal и организационно одобрение**.
