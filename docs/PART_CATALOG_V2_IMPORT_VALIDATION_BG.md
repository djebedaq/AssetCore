# Валидация на authoritative каталога `PARTS_CATALOG_V2`

## Резултат

Deterministic validator-ът `backend/scripts/catalog_v2_validation.py` потвърждава **611** source реда от точно **9** контролирани файла. Резултатът е записан машинно в `docs/PART_CATALOG_V2_IMPORT_VALIDATION.json`: `valid=true`, без грешки и предупреждения.

| Семейство | Възел | Source файл | SHA-256 | Страници | Редове |
|---|---|---|---|---:|---:|
| FALCH_500 | Wheel Jet | `FALCH_500/WHEEL_JET_PARTLIST.pdf` | `baab518592c770457ba493d056e7e7112ddfa15d45d8db93214fe339ec36af85` | 10 | 147 |
| FALCH_500 | Pump | `FALCH_500/PUMP_PARTLIST.pdf` | `0f9d3e8d178272b7e65a57a37f495a448fc24c31730ac2c107e5d50f29a317c4` | 4 | 65 |
| FALCH_500 | Unloader Valve | `FALCH_500/UNLOADER_VALVE_PARTLIST.pdf` | `5382954ff92c616622b0d4cfdc3a2a12581f442c209c6329d8d2e50cb40fc1d5` | 4 | 65 |
| FALCH_500 | Valve 500 bar | `FALCH_500/VALVE_500BAR_PARTLIST.pdf` | `ff4a643c60109636e6ebc619551d46ab57b05542fca32a46e3390dec130d14af` | 3 | 32 |
| FALCH_1000 | Wheel Jet | `FALCH_1000/WHEEL_JET_PARTLIST.pdf` | `acc612f796ec891cf8aeb0bc86b7150630f7b4874ea370d0c4f5503aff73675d` | 11 | 164 |
| FALCH_1000 | Drive Pump | `FALCH_1000/PUMP_PARTLIST.pdf` | `81eb5c94e2c2c2a2b8e868acb3721dddfecd642c2744093046fe34fdf9213c82` | 3 | 34 |
| FALCH_1000 | Liquid Part | `FALCH_1000/LIQUID_PART_PARTLIST.pdf` | `a238920e0392b9c5be56452eef1da9187e530d8dea6925b721784b06418a5278` | 4 | 46 |
| HYDWIN/Fussen | scope control | `HYDWIN_FUSEEN_500/READ BEFORE OPEN PDF.txt` | `a3b2978236b8a6c3418fe1738a76edec368ed2c88f6779cb4f57bf4fececdad9` | — | 0 |
| HYDWIN/Fussen | Plunger Pump | `HYDWIN_FUSEEN_500/ONLY_PLUNGER_PUMP.pdf` | `5b5d89b5ebcd71dc8f203d7a6ef419e9f131eaf7f95a1cbe3221992d5c6b7056` | 23 | 58 |

Общо по семейства: FALCH_500 — **309**, FALCH_1000 — **244**, HYDWIN_FUSSEN_500 — **58**.

## Scope и regression anchors

HYDWIN/Fussen импортът използва само PDF страница 21 за exploded view и страница 22 за BOM. Validator-ът отказва записи от други страници. Потвърдени са точно 58 позиции и anchors 13, 15, 34 и 35, включително `7.906-007.11 — Main water seal — 15*24*9.3 — qty 3`.

Falch anchors са проверени за Valve 500 bar позиции 3/4 и Liquid Part позиции 6/16. Трите официални `Replaced by` връзки се пазят отделно и старият номер остава търсим.

## Комплекти и схеми

- Repair kits: **7**.
- Source-linked kit components: **84**.
- Exploded diagram pages: **12**.
- Визуално проверени position-centric hotspots: **6**.
- Distinct source positions без проверена координата: **577** от общо 583.

Непроверените координати не са предполагани. Всички 611 реда остават достъпни чрез официалната позиционна таблица, а hotspot се показва само когато координатата е ръчно потвърдена.

## Възпроизводима проверка

```powershell
$env:PYTHONPATH='backend'
backend/.venv/Scripts/python.exe backend/scripts/catalog_v2_validation.py --json docs/PART_CATALOG_V2_IMPORT_VALIDATION.json
```

Validator-ът проверява наличие, SHA-256, PDF page count, допустими страници, source identity, anchors, family compatibility, orphan компоненти/hotspots и точните агрегирани бройки.
