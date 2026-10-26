# Матрица на действителните документи

Пет разновидности × BG/EN/RU × 1/5/30 реда = 45 входни случая. Всеки има `legacy.docx`, `legacy.pdf`, `studio.docx`, `studio.pdf`, всички page PNG, side-by-side PNG и `comparison.json`. Агрегатът е `comparison-results.json`. При transfer пълният snapshot е десет позиции; параметърът 1/5/30 не измисля допълнителни контролни позиции.

| Разновидност | Native договор | Проверявани бизнес области |
|---|---|---|
| transfer-issue | v3 | issue checklist, condition, purpose, remarks, identity, slots, header/footer |
| transfer-return | v3 | отделен return checklist, findings, identity, slots, header/footer |
| repair-protocol | v6 | acceptance/completion, diagnosis, required/performed work, parts, participants, recorded labor, stage durations, result, attachments, slot |
| kk-machine | source v3 + programmatic v3 | machine snapshot, 4 columns, request metadata, number/date/approver |
| kk-free | source v3 + programmatic v2 | no machine table, 3 columns, decimal quantity/unit, shared number/date/approval |

Измерванията проверяват равенството на DOCX text nodes, PDF text, page counts и растера на всяка страница при един и същ действителен converter. Растерното равенство не доказва универсално поведение във всеки Word/PDF viewer. DOCX ZIP bytes могат да се различават заради manifest и package metadata.

Отделните regression tests проверяват shared numbering, source failure rollback, canonical variant contradictions, protected markers, custom category labels, original images, immutable manifests, permissions, preview без ORM промени и архивите след company/machine/template промяна. Native official approval сценарият включва синтетични каталожни приложения, за да провери реалния appendix pipeline.

Подписите се сравняват като слотове и bindings; синтетичните preview линии не са реални графични подписи. Публичните screenshots и файлове не съдържат частния KK образец.
