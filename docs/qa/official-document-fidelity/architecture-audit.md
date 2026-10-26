# Архитектурен одит на официалните документи

Baseline: `0b03100f2021560eba296459cd2f43156de5f624` (актуален `origin/main` при започване). Анализът е записан преди имплементацията. Production база, конфигурация и архиви не са използвани. Следователно този документ установява договора на кода, а не активната конфигурация на конкретна инсталация.

## Действителни генератори

| Документ | Данни и източник | Избор и фиксиране | PDF и архив | Подписи и рискове |
|---|---|---|---|---|
| Предаване | `transfer_documents._protocol_template_values`, issue checklist и участници; контролиран `transfer_issue-*-v3.docx` | `_template_version`: последна StudioActivation или публикуван, валидиран legacy с effective dates; материализиране при операцията | `render_docx` попълва native DOCX; LibreOffice, при legacy отказ има отделен ReportLab fallback; ProtocolDocument и OfficialDocumentVersion пазят байтовете и snapshot | Съществуващи protected markers, участници, signature sessions и финализиране; legacy фиксирани 10 реда не са универсален checklist |
| Връщане | Същият модул, но return checklist, condition, findings, участници и дата; `transfer_return-*-v3.docx` | Отделен тип и отделна избрана версия; return snapshot, не issue snapshot | Същият механизъм; архивът не се регенерира от текущата машина | Същото подписване; трябва да се запазят двете отделни исторически състояния |
| Ремонт | `repair_documents.make_repair_documents`; repair, events, parts, participant name/title snapshots, записани минути, attachments; `repair_protocol-*-v6.docx` | Избор при приключване; correction създава нова версия чрез контролирана промяна на current_version | `render_docx`, native таблици с marker rows; LibreOffice или legacy ReportLab fallback; OfficialDocumentVersion | Вътрешен протокол с една защитена позиция; трудът на участниците и продължителностите на етапите са отделни величини |
| KK към машина | `official.capture_data` и `RequestApprovalSnapshot`; registered source `part_request-*-v3.docx` е контейнер | Единна транзакционна KK последователност; `document_layout_version=3`; machine, lines, company header, source bytes и hash при approval | `request_issue_documents.build_docx` → `request_layout_v2.build_docx` + machine section + frozen appendix; същият DOCX → PDF; savepoint при архивиране | Одобрил е бизнес доказателство, не автоматично графичен подпис; Studio добавя съществуващите protected markers, без втори signing механизъм |
| Свободна KK | Каноничен `request_kind=FREE_FORM`, точен Decimal текст и единица; същият бизнес тип PART_REQUEST | Същият counter/approval; `document_layout_version=2`; няма машина | Същият програмeн renderer, три колони, без machine table и catalog appendix | Вариантът трябва да идва от immutable данните, никога от UI избор при официално издаване |

## Разграничение на версиите

DocumentTemplateVersion.version е версия на регистрирания source. StudioActivation е append-only избор с отделна revision. Legacy template effective dates участват в default selection. Програмното KK оформление е отделен кодов договор v2/v3. Approval snapshot съдържа замразени template bytes, header resources и бизнес стойности. GeneratedDocument и OfficialDocumentVersion пазят издадените файлове и hashes. Нито една от тези величини не трябва да бъде преименувана или преномерирана с тази задача.

`templates.legacy_template_version` проверява language, publication, validation, effective dates и active template. При explicit StudioActivation `_template_version` проверява kind/type/language/publication/validation; няма fallback при невалиден explicit selection. Без избор е възможна двусмисленост между два legacy регистъра с еднакви версии; диагностиката трябва да я покаже.

## Потвърдени референции

Предоставените частни DOCX са достъпни. SHA-256 съвпадат: legacy source `ab76dddc2fe3c0b644ae91aeaa45c0ce4192bdfc8571975dcb40597387202ed0`; реална KK референция `f0a29f8d6c490a500bf55c32203d26755294289bb5087d8daf937964e614765a`. Проверена е структурата без публикуване на лични/бизнес стойности. Реалният KK има margins 48/12.7/12.7/12.7 mm, machine table 4×4, lines table 2×4 и footer table 1×3; legacy source има друго тяло и margins. Частните файлове не са копирани в repository или QA artifacts.

## Открити проблеми преди имплементация

1. `build_draft` приема legacy base_version_id, но оставя professional starter. Няма faithful conversion или compatibility отказ.
2. Studio schema 3 няма каноничен machine/free вариант; professional starter има постоянна машинна секция и request columns.
3. `issue_number` поглъща template selection/source грешки и запазва approval без source bytes; `archive` после избира текущ шаблон. Това може да промени документа след approval.
4. `capture_data` свързва snapshot lines и сортираните live lines чрез zip, въпреки че първият списък е от relationship order; необходима е проверка за стабилно свързване по ID.
5. `preview_pdf` за неподписана KK използва legacy layout независимо от избран Studio source.
6. Version preview отказва legacy sources; source download и actual generated layout не са ясно разграничени за администратора.
7. Старите fidelity artifacts сравняват professional starter, а не действителните approved legacy contracts; те не доказват текущата задача.
8. Controlled Repair v6 няма REPAIR_EVENTS table и CREATION_DATE field, докато Studio publication изисква и двете. Не трябва да се добавя измислено съдържание за прикриване на тази разлика.

## Архитектурно решение

Конверсията трябва да запазва native OOXML договора на известния source, включително таблици, styles, headers/footers, pagination и relationships. Програмните KK v2/v3 трябва първо да се материализират чрез действителния renderer с типизирани field/table markers. Редакторският модел може да е контролирана native структура с editable projections; неподдържана структура или редакция изисква конкретен compatibility отказ. Generic starter не е конверсия.

Двата KK варианта трябва да бъдат част от един immutable manifest и една публикация. Backend валидира двата, а renderer избира от `request_kind` и frozen `machine`; противоречие се отказва. Preview на всеки вариант използва същия renderer, без counter, request, signature session или запис на official archive.

Издаване без проверен approval source се отказва безопасно. Старите вече архивирани байтове продължават да се връщат без регенериране. Исторически approvals без source могат да останат с ясна generation failure, без подмяна с текущ шаблон. Не се пренаписва snapshot.

Безопасна read-only диагностика трябва да връща selection, legacy candidates, source hash, programmatic layout versions, publication dates и activation revision, без бизнес записи, filesystem paths или тайни. Не се създава втори регистър.

## Security и concurrency договор

Съществуващите permissions (`studio.view`, `templates.manage`, `company.manage`), CAS draft revision, preview receipts, append-only activations и database guards остават авторитетни. Новите конверсия/preview endpoints трябва да използват същите проверки. DOCX ingestion остава bounded и забранява external relationships, executable content, unsafe XML и неподдържани field instructions. Подписните slots не могат да бъдат преместени или дублирани чрез свободен текст.

Approval counter и snapshot са в caller transaction. Archive generation е в savepoint и не отменя вече издадения номер при renderer failure. Тестовете трябва да проверят PostgreSQL, SQLite, повторно генериране, едновременни approval/activation/publication и failed finalization. Няма основание за schema migration само за versioned JSON layout.

## Фази и блокиращи доказателства

Следват имплементация, DOCX/PDF сравнения на еднакви синтетични данни за петте варианта и BG/EN/RU, втори review, browser QA, preservation и петте CI jobs. Наличието на valid PDF само по себе си не е fidelity доказателство. Непроверена визуална или PostgreSQL/CI проверка остава блокираща за READY.
