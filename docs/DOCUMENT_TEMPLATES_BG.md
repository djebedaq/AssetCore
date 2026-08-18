# Документни шаблони и контрол на визуалното качество

## Източници

Снимките в `backend/resources/reference_photos` са визуалните образци за приемане/предаване и parts requests. Контролираните DOCX layout източници са `backend/resources/reference_protocols/controlled_repair_layout_reference.docx` и `controlled_parts_request_layout_reference.docx`. Те са read-only references и съдържащите се исторически записи никога не се копират като нови бизнес факти. Папката `technical_docs/PARTS_CATALOG` съдържа само authoritative каталожни източници и не се използва като document-template library.

## Генериране

- Issue/return: A4 portrait по реалния снимков образец, тройна фирмена шапка KRZ/ODESSOS/RINA, protocol title, машинен snapshot, точно десет checklist реда, общо състояние, предназначение, бележки, подписи в оригиналните клетки и batch trace. При нормално съдържание DOCX/PDF са една страница; отделна страница за потвърдени подписи не се добавя.
- Repair v6: общ тричастов комплект — (1) проблем/състояние/демонтаж/диагностично почистване/необходим ремонт/диагностика, (2) извършени дейности и вложени части, (3) stage/participant времена, тест, краен резултат, приложения и приемане. Първата страница използва byte-level същите embedded company header media като approved transfer v3, без промяна на transfer шаблоните.
- Parts request: компактна technical-specification форма, машинен block само при linked asset, четири колони за записаните редове, provenance, request/date/requester/decision.
- Condition клетките не се попълват автоматично. `READY`, използвани части, получател, местоположение и подписи не се измислят.

Всеки generated document пази content, SHA-256, snapshot, machine/transfer/batch/repair/request links, template version, language, creation date и actor. Повторно генериране добавя version suffix и не заменя по-стария файл.

## Управление на версии

Seed-ът регистрира BG/EN/RU машинно използваеми transfer DOCX v3 и repair DOCX v6 шаблони, както и останалите контролирани шаблони с отделен човешки текст, SHA-256 и validation report. `Топтоптоп.docx` е използван само като външна съдържателна референция; в repository не се копират негови хора, машини, части, дати или други бизнес записи. Снимките и историческите документи са provenance reference, не executable template и не нов бизнес факт.

Нова версия се качва през Administration като DOCX и съдържа език, начало/край на валидност, задължителни полета, правило за номерация, отдел, layout contract и описание на промяната. Server-ът изчислява SHA-256 и проверява четим DOCX ZIP, `TEMPLATE_LANGUAGE`, `DOCUMENT_NUMBER`, `SIGNATURE_STATUS`, съставител, required fields и забраната за `reference_only`. Issue/return/part-request шаблоните изискват двете си подписни позиции; вътрешният repair v6 използва реалния responsible/approver контекст и finalized internal signature status. Невалиден файл остава `FAILED` и не може да бъде публикуван.

Генераторът зарежда exact bytes на избраната версия и попълва placeholders/tables. Неизвестен или останал placeholder прекратява цялата бизнес транзакция. Production PDF се конвертира от същия попълнен DOCX с LibreOffice. Локалният ReportLab fallback се отчита изрично и не е доказателство за визуална DOCX/PDF идентичност.

При генериране се използва само публикувана версия за точния език и в активния ѝ период. Ако такава липсва, официалният документ не се създава, транзакцията се връща изцяло и потребителят получава предложение да използва потвърдения български шаблон. Промяната на текущ шаблон не засяга старите документи, защото те пазят точния `template_version_id`, съдържанието, snapshot-а и hash-а си.

## QA процедура

Изолираната проверка не използва configured production database:

```powershell
backend/.venv/Scripts/python.exe backend/scripts/document_qa.py <output-directory>
```

Скриптът генерира четири DOCX/PDF двойки и `qa-manifest.json`, проверява sections/tables/margins/package parts, hashes и byte-level запазване на embedded header media. Оригиналните reference hashes трябва да останат:

- controlled historical repair DOCX reference: `39337dfc445d61b4d5144259ca35624c2049d266378e326780176de3104784c1`;
- executable repair BG v6 template: `89231f723dc6184f4a10a8f8682e59ba96f883d23087ad1008fc78f6d4673929`;
- parts-request DOCX: `3ba8e43102ae044b02b6aa7a4cd3b06ff00bce444a56fc8da6ba737c42bbc7a7`.

Рендерирайте всеки PDF до PNG и проверете всички страници за clipping, overlap, повредена кирилица, разкъсани таблици и неочаквана pagination. DOCX трябва да се рендерира с Word/LibreOffice. Ако headless renderer липсва или блокира, package-level проверката е валиден fallback, но DOCX визуалното рендериране се отчита честно като непотвърдено.


## Transfer шаблони v3

Шаблоните се възпроизвеждат с `python scripts/generate_transfer_templates.py`. Те съдържат скрити машинни маркери за двете подписни позиции. При финализиране маркерите се заменят с криптографски обвързаните графични подписи в същите клетки. Ако DOCX→PDF конверсията е налична, PDF се създава от подписания DOCX; fallback-ът поставя подписите върху първата страница и не създава annex.
