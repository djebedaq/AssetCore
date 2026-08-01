# Документни шаблони и контрол на визуалното качество

## Източници

Снимките в `backend/resources/reference_photos` са визуалните образци за приемане/предаване и parts requests. Реалните DOCX в `backend/resources/technical_docs/protocols_hpwj` и `parts_requests_hpwj` са package/style/header източници. Те са read-only references и съдържащите се исторически записи никога не се копират като нови бизнес факти.

## Генериране

- Issue/return: A4 portrait, тройна фирмена идентичност, protocol title, машинен snapshot, точно десет checklist реда, общо състояние, предназначение, бележки, подписи и batch trace.
- Repair: фирмен header, before/problem/diagnosis/work/event/part/test/after секции и подписи; снимки само ако са качени към ремонта.
- Parts request: компактна technical-specification форма, машинен block само при linked asset, четири колони за записаните редове, provenance, request/date/requester/decision.
- Condition клетките не се попълват автоматично. `READY`, използвани части, получател, местоположение и подписи не се измислят.

Всеки generated document пази content, SHA-256, snapshot, machine/transfer/batch/repair/request links, template version, language, creation date и actor. Повторно генериране добавя version suffix и не заменя по-стария файл.

## Управление на версии

Seed-ът публикува само четирите проверени български версии: издаване, връщане, ремонтен протокол и заявка за части. EN/RU записите са чернови и не са разрешение за официален преведен документ.

Нова версия се качва през Administration като защитен DOCX/PDF и съдържа език, начало/край на валидност, задължителни полета, правило за номерация, отдел, layout contract и описание на промяната. Server-ът изчислява SHA-256; browser-ът не подава вътрешен filesystem path. Версията остава чернова, докато administrator с `templates.manage` не изтегли изходния файл, не го сравни със снимковите и оригиналните фирмени образци и не потвърди публикуването с отделно действие.

При генериране се използва само публикувана версия за точния език и в активния ѝ период. Ако такава липсва, официалният документ не се създава, транзакцията се връща изцяло и потребителят получава предложение да използва потвърдения български шаблон. Промяната на текущ шаблон не засяга старите документи, защото те пазят точния `template_version_id`, съдържанието, snapshot-а и hash-а си.

## QA процедура

Изолираната проверка не използва configured production database:

```powershell
backend/.venv/Scripts/python.exe backend/scripts/document_qa.py <output-directory>
```

Скриптът генерира четири DOCX/PDF двойки и `qa-manifest.json`, проверява sections/tables/margins/package parts, hashes и byte-level запазване на embedded header media. Оригиналните reference hashes трябва да останат:

- repair DOCX: `39337dfc445d61b4d5144259ca35624c2049d266378e326780176de3104784c1`;
- parts-request DOCX: `3ba8e43102ae044b02b6aa7a4cd3b06ff00bce444a56fc8da6ba737c42bbc7a7`.

Рендерирайте всеки PDF до PNG и проверете всички страници за clipping, overlap, повредена кирилица, разкъсани таблици и неочаквана pagination. DOCX трябва да се рендерира с Word/LibreOffice. Ако headless renderer липсва или блокира, package-level проверката е валиден fallback, но DOCX визуалното рендериране се отчита честно като непотвърдено.
