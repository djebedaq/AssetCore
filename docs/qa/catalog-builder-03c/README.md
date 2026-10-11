# Catalog Builder 03C — проверими QA резултати

[Технически отчет](../../CATALOG_BUILDER_03C_BG.md), [local verification](verification.json),
[реален D13 UI](browser-d13.json), [Linux exact-field regression, 3 прогона](d13-linux-exact.json),
[синтетичен UI acceptance](browser-synthetic.json).

Screenshots са от реалния Edge браузър и нормалните API върху отделна SQLite QA база.
В тях се използва само генерираният синтетичен PDF от тестовия runner; не са mockups.
Сценарият включва два реални таба: stale autosave, блокирано остаряло потвърждение
с нула създадени части и безопасно възобновяване след изрично презареждане на променения ред.

| Изглед | Screenshot |
|---|---|
| Избрани PDF страници | [1440 px](sources-1440.png) |
| Единна таблица и оригинално evidence | [1440 px](parts-1440.png), [768 px](parts-768.png), [390 px](parts-390.png) |
| Десет действителни синтетични callouts | [Hotspots](hotspots-1440.png) |
| Server readiness след source review и verified hotspots | [Final review](ready-1440.png) |

OEM PDF, expected JSON и OEM screenshots остават локални. Exact-field JSON съдържа само
сравнения, fingerprints и измервания, без оригинални OEM редове/изображения.
Expected JSON се използва отделно след extraction. Успешната синтетична публикация не е
твърдение за готовност на D13 hotspots или за разрешаване на разминаването 48/38.

Пълните SQLite/PostgreSQL, dependency-security и image checks са в **Build check** върху
последния PR HEAD. Финалният технически отчет в PR посочва точните CI резултати.
