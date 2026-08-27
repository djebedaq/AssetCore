# Официални документи и шаблони

Template registry използва стабилен template ID, document type, language,
version, относителен source path/bytes, SHA-256, validation report и publication
status. Свободното Unicode име не се използва като идентификатор. Публикуване е
възможно само след проверка на DOCX структурата, езика, версията, document
number, preparer, required placeholders/fields, signature positions и source
hash. `reference_only`, липсващ или повреден source се отказва.

DOCX започва от точните bytes на избраната публикувана версия. PDF се конвертира
от същия попълнен DOCX в production. Всеки `GeneratedDocument` и
`OfficialDocumentVersion` пази template/version/source hash, language, business
snapshot, preparer, creation time и file hashes. Генерирането не презаписва
съществуващ номер.

`OfficialDocument.current_version_id` се задава само през централизирания
integrity service. Database guard-ът изисква сочената версия да съществува и
нейният `document_id` да съвпада с документа. Исторически malformed pointer не
се поправя чрез измислена версия или повторно генериране: registry read остава
толерантен, а read-only validator го отчита като `TOLERATED_HISTORY`.

Официалният поток е draft → участници/signature slots → preview → подписи →
finalized signed version. Достъпни са индивидуални DOCX/PDF download-и, status,
version history и hash verification. Подписана версия не се редактира и не се
анулира; supersede създава версия N+1 с причина и връзка към предишната.

Имплементацията на генераторите е разделена в `backend/app/documents/`, без
промяна на този workflow. Старите imports от `app.document_generation` остават
валидни. Document builders регистрират версията чрез съществуващия integrity
service и връщат файловите записи, но не правят commit — транзакцията принадлежи
на извикващия workflow. Картата на модулите и доказателствата за запазено
съдържание са в [DOCUMENT_MODULARIZATION_BG.md](DOCUMENT_MODULARIZATION_BG.md).

Екранът „Официални документи и подписи“ е централен read-only регистър, а не
алтернативен генератор или signing workflow. Той показва отделно lifecycle-ите
за приемане/предаване, ремонтните протоколи и протоколите за заявени части,
използва точните съществуващи номера и current immutable versions и запазва
legacy download достъпа без duplicate presentation. Отварянето или изтеглянето
не създава версия и не променя snapshot, hash, подпис или audit history.

Издаването и връщането регистрират immutable snapshot и участниците в самата
операция. До пълното подписване документите не се публикуват за download и
машината не се премества. Manual `POST /api/official-documents` не приема
transfer document types, за да няма втори паралелен начин за същия протокол.
Приключването на вътрешен ремонт автоматично създава заключен `FINALIZED`
DOCX/PDF без handover/acceptance подписи. Корекцията изисква основание и създава
нова версия чрез repair correction endpoint; старата остава достъпна.

За QA изпълнете `backend/scripts/document_qa.py <изолирана-папка>`. Скриптът
генерира DOCX/PDF само във временна QA база, проверява кирилица, placeholders,
document number, signature status, templates и hashes, и връща ненулев exit code
при критична грешка. В production release изображенията на страниците трябва да
се сравнят със снимковите образци чрез LibreOffice/Poppler.
