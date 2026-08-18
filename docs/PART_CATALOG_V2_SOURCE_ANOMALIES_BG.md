# Source anomalies в `PARTS_CATALOG_V2`

Този отчет описва необичайните стойности точно както присъстват в authoritative документите. Те не са „поправяни“ чрез предположение.

## Празни part codes

В HYDWIN/Fussen Plunger Pump BOM позициите **1**, **2** и **29** имат празен code. Записите се пазят с празен `part_number`, собствен `source_record_key` и anomaly `BLANK_PART_NUMBER`; UI показва, че номер липсва, вместо да измисля такъв.

## Необичайно количество

HYDWIN/Fussen позиция **22**, code `7.906-010.4.5.6`, съдържа quantity `1 each`. Запазено е `quantity_raw="1 each"`, numeric quantity остава `NULL`, а заявеното количество се определя от оператора.

## Повтарящи се позиции

Общо **46** source реда са маркирани `REPEATED_POSITION_VARIANT`. Те образуват следните position groups и не се сливат:

- `falch_500_pump`: 0 (7 реда), 5, 10, 32 и 40 (по 2);
- `falch_500_unloader_valve`: 0 (3);
- `falch_500_valve_500bar`: 800 (4);
- `falch_500_wheel_jet`: 2, 4 и 29 (по 2), 82 (3);
- `falch_1000_drive_pump`: 15, 25 и 28 (по 2);
- `falch_1000_liquid_part`: 36 (3);
- `falch_1000_wheel_jet`: 20, 22 и 95 (по 2).

Различията в `part_number`, `quantity_raw`, `valid_for_raw` или source row identity се пазят. Position-centric hotspot връща всички variants и изисква избор, когато са повече от един.

## Официални заместители

Запазени са точно три source relations:

- `E0111569-R` → `E0112546`;
- `E0112546` → `E0112917`;
- `E1220030-R` → `E1220041`.

Това не е редакция на source реда. Каталогът показва оригиналния и актуалния номер; заявката използва `replaced_by_part_number`, като пази връзката към оригиналния каталожен запис.

## Непроверени hotspot координати

Проверени са само шест координати: Falch 500 Valve позиции 3/4, Falch 1000 Liquid Part позиции 6/16 и HYDWIN позиции 34/35. За останалите 577 distinct позиции не са създавани предполагаеми координати. Изборът от source таблицата остава пълноценният безопасен fallback.
