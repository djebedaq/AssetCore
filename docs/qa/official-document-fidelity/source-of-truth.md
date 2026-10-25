# Източници и граници на доказателствата

Baseline: `0b03100f2021560eba296459cd2f43156de5f624`. Няма достъп до Production. Версията в конкретна инсталация се установява с `GET /api/studio/configuration/{document_type}/{language}` от потребител с `studio.view`; отговорът е `private, no-store` и не създава бизнес записи.

| Слой | Авторитетно доказателство |
|---|---|
| Регистриран източник | DocumentTemplateVersion: ID, version, language, source_sha256, проверени source bytes |
| Публикуване | is_published, validation_status, published_at, effective_from/effective_to |
| Избрана версия | Последната append-only StudioActivation, selection_kind и revision; без избор — единствената най-висока допустима legacy версия |
| Програмно оформление | KK MACHINE v3 / FREE_FORM v2; source v3 е входен контейнер |
| Одобрение | RequestApprovalSnapshot: template_content, source hash, machine/lines/header evidence |
| Издаден документ | GeneratedDocument и OfficialDocumentVersion, действителни DOCX/PDF bytes и hashes |
| Подпис | Съществуващите защитени позиции, signer identity, version hash и signature session |

Изрично невалиден или двусмислен избор отказва операцията. Одобрение без проверени template bytes се отказва преди резервиране на KK номер. Архивираните байтове се връщат директно. Стар snapshot без template evidence не се поправя чрез текущия шаблон.

Контролираният adapter 1 / schema 4 допуска само hash-потвърдените transfer issue/return v3, repair v6 и part request v3 на BG/EN/RU. За KK първо материализира истинския програмeн layout с typed markers; запазва двата варианта в един immutable manifest. За другите типове запазва оригиналното OOXML. Защитените позиции и структурата не могат да се преместят или заличат. Неподдържана конверсия връща `studio_native_incompatible`.

## Частни контролни образци

И двата предоставени DOCX са достъпни и SHA-256 съвпадат с посочените в заданието. Реално са конвертирани и визуално прегледани всички страници: KK — три; source — една. Прегледът потвърждава тройната шапка, четириколонната спецификация и двете отделни каталожни приложения в крайния KK, докато източникът има друго тяло и placeholders. Частни имена, машинни стойности и каталожни изображения не са пренасяни в QA. Оригиналите и техните частни рендери остават извън Git.

Публичната матрица използва само синтетични стойности. Равенството е между изпълнените legacy и Studio генератори при еднакъв вход; не е сравнение с частния бизнес документ и не доказва състоянието на Production.
