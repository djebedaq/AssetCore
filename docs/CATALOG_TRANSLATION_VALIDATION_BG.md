# QA отчет — EN/BG наименования в authoritative каталога

## Обхват и модел на данните

Активният non-authoritative enrichment е `CATALOG_EN_BG_V1`. Той не променя `PARTS_CATALOG_V2`, оригиналните PDF файлове или извлечените от тях полета. Всеки от 611-те display записа е свързан чрез пълния canonical `source_record_key`; Part No. не се използва като идентичност, защото има повторени позиции, варианти и три source реда с празен Part No.

Терминологията е versioned в `backend/resources/catalog/enrichment/v1/terminology_en_bg.json`. Детерминистичният `backend/scripts/build_catalog_translations.py` разрешава всяко source English понятие само чрез изрично проверен термин и генерира `catalog_names_en_bg.json`. Липсващ или неизползван термин прекратява build-а; няма автоматичен fallback или машинен превод по време на работа.

## Валидирани метрики

| Метрика | Резултат |
|---|---:|
| authoritative catalog records | 611 |
| EN display coverage | 611 |
| BG display coverage | 611 |
| orphan translations | 0 |
| missing translations | 0 |
| duplicate canonical translation keys | 0 |
| `VERIFIED` translation records | 603 |
| `NEEDS_REVIEW` translation records | 8 |
| authoritative source fingerprints | 9/9 непроменени |
| mapped unique positions | 581 |
| hotspot occurrences | 818 |
| duplicate callout occurrences | 237 |
| unresolved printed positions | 0 |
| verified positions not drawn | 2 |
| repair kits / components | 7 / 84 |

Валидаторът проверява non-empty EN/BG имена, exact canonical coverage, orphan/duplicate/missing идентичности, QA status и бележка, binding към деветте manifest SHA-256 стойности и реалния SHA-256 на всеки source файл.

## Терминологични правила

- Original manufacturer description се пази отделно и се показва само като source detail.
- Normal UI показва `English / Български` чрез един frontend helper и canonical API DTO.
- Използвана е консистентна HPWJ терминология: `Hose / Шланг`, `Valve seat / Седло на клапана`, `O-ring / О-пръстен`, `Unloader valve / Разтоварващ клапан`.
- Явни source грешки в display слоя са нормализирани без промяна на source: `throstle` → `Throttle / Дросел`, `kreuzstück` → `Cross fitting / Кръстат фитинг`, `crosstail` при source `kreuzkopf` → `Crosshead / Кръстата глава (крейцкопф)`.
- Спецификации, резби и налягания в дългите наименования са запазени; отделното source specification поле остава непроменено.

## Случаи `NEEDS_REVIEW`

Тези имена са попълнени, но не се представят като окончателно технически потвърдени извън наличния source контекст:

| Canonical identity | Display name | Причина |
|---|---|---|
| `hydwin_fussen_500_plunger_pump:p22:r057` | 45-degree open washer / Отворена шайба 45° | Source не посочва стандарт или по-точен тип на шайбата. |
| `hydwin_fussen_500_plunger_pump:p22:r014` | Air cap gasket / Уплътнение на въздушната капачка | Source не уточнява функцията на конкретната air cap. |
| `falch_500_unloader_valve:p3:r001:28:E0990027` | Control knob / Регулираща ръкохватка | `Griff/knob` не определя еднозначно геометрията на ръкохватката. |
| `falch_500_wheel_jet:p4:r025:23:S270` | Rubber element / Гумен елемент | Source дава само материал и размери, не функция. |
| `falch_1000_wheel_jet:p4:r029:27:E1000070` | Rubber element / Гумен елемент | Source дава само материал и размери, не функция. |
| `falch_1000_wheel_jet:p7:r005:85:S270` | Rubber element / Гумен елемент | Source дава само материал и размери, не функция. |
| `falch_500_valve_500bar:p2:r023:23:E0800545` | Point-jet nozzle 0°… / Точкова дюза 0°… | German source име посочва 500 bar, а English колоната — 3000 bar; display името не избира една от конфликтните стойности. |
| `falch_1000_wheel_jet:p6:r021:79:E1300037` | Pressure screw 3000 bar… / Притискателен винт 3000 bar… | English source име посочва 24 mm, а German името и specification — 19 mm; display името пропуска конфликтната дължина. |

Промяна от `NEEDS_REVIEW` към `VERIFIED` изисква човешка проверка спрямо контролирания документ и versioned промяна в терминологията и генерирания ресурс.

## Regression anchor

HYDWIN позиция 34 е свързана чрез `hydwin_fussen_500_plunger_pump:p22:r034` и се показва като `Main water seal / Основно водно уплътнение`. Source стойностите остават: Part No. `7.906-007.11`, specification `15*24*9.3`, original description `Main water seal`.

## Команди

```text
PYTHONPATH=backend python backend/scripts/build_catalog_translations.py --check
PYTHONPATH=backend python backend/scripts/catalog_v2_validation.py
python -m pytest -q tests/test_catalog_translations.py tests/test_verified_part_catalog.py
```
