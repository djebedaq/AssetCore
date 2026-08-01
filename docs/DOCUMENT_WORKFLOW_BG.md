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

Официалният поток е draft → участници/signature slots → preview → подписи →
finalized signed version. Достъпни са индивидуални DOCX/PDF download-и, status,
version history и hash verification. Подписана версия не се редактира и не се
анулира; supersede създава версия N+1 с причина и връзка към предишната.

За QA изпълнете `backend/scripts/document_qa.py <изолирана-папка>`. Скриптът
генерира DOCX/PDF само във временна QA база, проверява кирилица, placeholders,
document number, signature status, templates и hashes, и връща ненулев exit code
при критична грешка. В production release изображенията на страниците трябва да
се сравнят със снимковите образци чрез LibreOffice/Poppler.
