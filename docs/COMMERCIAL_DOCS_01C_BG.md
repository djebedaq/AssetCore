# COMMERCIAL DOCS 01C — предложения и финален Document Studio UX

Base: `48600622f6bc69d9783ad0e119cf379699f71e31`. Етапът използва съществуващите DocumentTemplate, DocumentTemplateVersion, DocumentEditorDraft и StudioActivation. Няма втори регистър на шаблони, автоматична публикация, автоматично активиране, merge или deployment.

## Управленски workflow

Директорът избира конкретна версия от библиотеката и изпраща заглавие, описание и до три безопасни изображения. Backend проверява връзките template/version/language и разрешението `studio.propose`; непознати структурни полета се отхвърлят. Директорът вижда/коментира само собствените предложения. Администраторът/собственикът управлява всички предложения чрез съществуващото `templates.manage`.

Новото предложение е PENDING. Приемане и отказ изискват мотив. Атомарен UPDATE по id/revision допуска само един конкурентен запис; остарялото действие връща 409. Прието предложение остава ACCEPTED и след публикация. Решението никога не публикува/активира шаблон.

Черновата наследява точния immutable manifest на target Studio версията. По-нова версия от същия шаблон/език може да се избере изрично. Reference-only DOCX не се подменя автоматично със starter или активен шаблон. Релационната връзка предложение → чернова → публикувана версия се записва чрез draft link и PUBLISHED event в същата транзакция с публикацията.

## Добавъчна миграция 0039

| Таблица | Предназначение |
|---|---|
| `studio_proposals` | Точни target/author/language, заглавие/описание, статус, ревизия, дата/потребител/мотив на решението |
| `studio_proposal_events` | Append-only CREATED/COMMENT/ACCEPTED/REJECTED/DRAFT_CREATED/PUBLISHED с автор, дата и FK към чернова/версия |
| `studio_proposal_attachments` | Отделни нормализирани PNG байтове/hash/размери; не CompanyBrandImage |
| `studio_proposal_drafts` | Неизменяема връзка към редакторска чернова и изрично избрана базова версия |

SQLite/PostgreSQL triggers забраняват промяна/изтриване на evidence редовете и изтриване на предложението; target, автор, текст и приключено решение не се пренаписват. Ревизията се увеличава точно с едно. Audit Log записва управленските действия. Downgrade отказва да изхвърли съществуваща история. Миграции 0001–0038 са непроменени.

## API

| Метод и endpoint | Право / поведение |
|---|---|
| GET `/api/studio/proposals` | studio.propose; собствен/административен обхват, търсене, статус/език/шаблон, bounded pagination и pending count |
| POST `/api/studio/proposals` | studio.propose; валидиран target и текст, изображения до 3 × 2 MB |
| GET `/api/studio/proposals/{id}` | Разрешен обхват, история до 100 събития; `before_revision` за по-стара история |
| GET `/api/studio/proposals/{id}/attachments/{attachment_id}` | Проверява и принадлежността към предложението; private/no-store/nosniff PNG |
| POST `/api/studio/proposals/{id}/comments` | Собствен автор или администратор; expected_revision и append-only коментар |
| POST `/api/studio/proposals/{id}/decision` | templates.manage; PENDING, expected_revision, решение и задължителен мотив |
| POST `/api/studio/proposals/{id}/drafts` | templates.manage; ACCEPTED, CAS, exact target или изрично по-нова съвместима Studio версия |
| GET `/api/studio/versions/{id}/preview` | studio.view; реален bounded DOCX→PDF от точния frozen Studio manifest, без мутация |

Няма proposal endpoint за редакция на layout JSON, публикуване, активиране, restore или изтриване на версия. PNG/JPEG decoder проверява действителния формат, пиксели, размер и кадри; премахва метаданни/добавен payload. SVG, активен код, path traversal и чужди attachment IDs се отхвърлят.

## Ограничени промени в съществуващия renderer/editor

Добавени са незадължително празно logo image_id, paragraph-before spacing, native table cell padding и AT_LEAST минимални височини. Липсващото лого заема празно печатно пространство; помощният надпис съществува само върху canvas. Обикновен image block продължава да изисква разрешено изображение. Старите frozen manifests остават съвместими и не се презаписват.

Компактно/Стандартно/Просторно се прилагат само към текущата чернова, през същите Undo/Redo, autosave, CAS и preview receipt. Header/footer резервите, image geometry, dynamic bindings, page-break/keep-together flags и защитените подписни слотове се запазват. Публикуването/активирането/legacy restore и официалното подписване използват съществуващите механизми.

За security gate се фиксират [Pillow 13.0.0](https://pypi.org/project/pillow/13.0.0/) и [certifi 2026.10.19](https://pypi.org/project/certifi/2026.10.19/); [pypdf 6.21.1](https://pypi.org/project/pypdf/6.21.1/) заменя 6.19.0. Audit policy и тестовите прагове не са понижавани.

## Документация и доказателства

- [Предварителен анализ](COMMERCIAL_DOCS_01C_ANALYSIS_BG.md).
- [Ръководство за нов клиент](DOCUMENT_STUDIO_GUIDE_BG.md).
- [Проверки преди бъдещо разрешено внедряване](COMMERCIAL_DOCS_01C_RELEASE_READINESS_BG.md).
- [QA отчет, реални DOCX/PDF/PNG и preservation](qa/commercial-docs-01c/README.md).

Reference-only DOCX import остава изрично ограничение. Предложенията нямат автоматични имейли или външни услуги. Архивните проверки се изпълняват в синтетични изолирани QA бази; не е използвана Production база.
