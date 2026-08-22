# Визуален каталог — текуща проверка

Този filename се пази за съвместимост със стари documentation links. Текущият визуален каталог е position-centric `PARTS_CATALOG_V2`; той не използва legacy CombiJet/Falch/HYDWIN source bundle.

Проверени са всички 12 diagram страници: 581 действително отпечатани позиции и 818 отделни области. Два BOM реда позиция `0` за цели възли проверено не присъстват като указатели. Текущите резултати и методът са в [CATALOG_POSITION_MAPPING_VALIDATION_BG.md](CATALOG_POSITION_MAPPING_VALIDATION_BG.md), а операторският workflow — в [OPERATIONS_PART_CATALOG_BG.md](OPERATIONS_PART_CATALOG_BG.md).

Production interaction договорът различава pointer типа: desktop mouse click отваря детайлите с едно действие, а touch използва stateful „първо докосване = избор / второ докосване на същата позиция = детайли“. Movement threshold и pinch state блокират случайно отваряне след pan, drag, swipe или pinch. Детайлите са focus-trapped modal на desktop и safe-area bottom sheet с отделен непревъртащ се header на mobile. Добавянето към заявка остава изцяло explicit.
