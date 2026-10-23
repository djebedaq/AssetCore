# Анализ преди COMMERCIAL DOCS 01C

Проверен main: `48600622f6bc69d9783ad0e119cf379699f71e31`. 01A/01B са интегрирани. Съществуващите DocumentTemplate/Version/Draft/StudioActivation остават единственият регистър. Разгледани са Studio backend/frontend, permissions, audit, каноничните генератори/официалния регистър, документацията на A/B и final-fidelity доказателствата на B.

| Област | Наличен договор | Решение за C |
|---|---|---|
| Права | Администраторът има templates.manage/company.manage; директорът studio.view | Отделно studio.propose; обхват собствен автор или администратор; без редакторски права за директора |
| Чернови и публикации | CAS, receipt за валидиран PDF, immutable публикация, отделен explicit activation/restore | Предложението пази точна target версия; прието предложение поражда отделна свързана чернова; публикацията добавя проследимо събитие в същата транзакция |
| Предложения | Няма управленски модел | Нормализирани proposal/event/attachment/draft-link таблици; PENDING/ACCEPTED/REJECTED; append-only история и CAS за решение/коментар/чернова |
| Изображения | normalize_image проверява PNG/JPEG, реален формат, пиксели/размер, премахва метаданни | Повторна употреба на безопасния decoder, отделно хранилище за proposal evidence; никога CompanyBrandImage/allowlist |
| Лого | Starter печата текстов заместител при липса на лого | Незадължителен logo block без image_id; canvas placeholder, празно печатно пространство; старите версии/legacy байтове остават неизменни |
| Компактност | Настроими block spacing/cell padding/min-height/fonts, native flow | Локални draft presets и paragraph spacing; Undo/Redo/CAS/preview остават същите; без глобална промяна на публикувани версии |
| Регресии | Реален DOCX→PDF, четири workflow, подписи, frozen KK, legacy restore, 256 protected files | Повторно изпълнение на B regression suite, нови role/IDOR/image/CAS/immutability/Chromium тестове и QA артефакти |

Референтният DOCX импорт остава reference-only. При non-Studio target се показва явен отказ за автоматично клониране; администраторът трябва изрично да избере съвместима Studio версия, без мълчаливо заместване с активната. Приемането не променя избор, шаблон или официален архив. Няма email, външни услуги, нов tenant слой, Production достъп или deployment.
