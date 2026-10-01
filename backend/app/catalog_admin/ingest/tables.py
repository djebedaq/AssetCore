"""Generic coordinate-aware BOM columns; uncertain values stay uncertain."""

import re
from decimal import Decimal, InvalidOperation

POSITION = re.compile(r"^(?:[A-Za-zА-Яа-я]?\d+(?:\.\d+)?[A-Za-zА-Яа-я]?|[A-Za-zА-Яа-я]\d+)$")
ALIASES = {
    "position": {"item", "pos", "position", "ref", "reference", "no", "nr", "позиция", "поз", "позиц", "позномер"},
    "part_number": {"part no", "part number", "spare part no", "article no", "art nr", "teile nr", "teil nr", "part nr", "номер детали", "номер част", "кат номер", "артикул", "номенклатурен номер"},
    "description": {"description", "designation", "name", "benennung", "beschreibung", "bezeichnung", "описание", "наименование", "название", "обозначение"},
    "quantity": {"qty", "quantity", "pieces", "pcs", "menge", "anzahl", "количество", "кол", "бр", "кол во"},
    "technical_specification": {"specification", "spec", "технически данни", "спецификация"},
    "technical_notes": {"notes", "note", "bemerkung", "забележка", "примечание"},
}


def normalize_header(text: str) -> str:
    return re.sub(r"[.№#:_\-/]+", " ", text.casefold()).strip()


def field_name(text: str) -> str | None:
    clean = " ".join(normalize_header(text).split())
    return next((name for name, aliases in ALIASES.items() if clean in aliases), None)


def quantity(raw: str) -> str | None:
    if not re.fullmatch(r"\d{1,10}(?:[.,]\d{1,4})?", raw.strip()):
        return None
    try:
        return str(Decimal(raw.replace(",", ".")))
    except InvalidOperation:
        return None


def make_row(values: dict, bbox: list[float], raw: str, *, method: str) -> dict | None:
    position = values.get("position", "").strip()
    uncertain_position = not POSITION.fullmatch(position)
    if uncertain_position and not (not position and values.get("part_number") and values.get("description") and quantity(values.get("quantity", "")) is not None):
        return None
    if not any(values.get(key) for key in ("part_number", "description")):
        return None
    warnings = []
    if uncertain_position:
        warnings.append("MISSING_POSITION")
    if any(len(value) > (80 if key == "position" else 120 if key in {"part_number", "quantity"} else 4000)
           for key, value in values.items()):
        warnings.append("FIELD_TOO_LONG")
    if not values.get("part_number"):
        warnings.append("MISSING_PART_NUMBER")
    if not values.get("description"):
        warnings.append("MISSING_DESCRIPTION")
    raw_qty = values.get("quantity", "").strip()
    numeric = quantity(raw_qty)
    if numeric is None:
        warnings.append("QUANTITY_UNCERTAIN")
    payload = {"position": position, "part_number": values.get("part_number", "").strip(),
               "description": values.get("description", "").strip() or None,
               "quantity": numeric, "quantity_raw": raw_qty or None}
    for key in ("technical_specification", "technical_notes"):
        if values.get(key):
            payload[key] = values[key]
    return {"payload": payload, "bbox": bbox, "raw_values": values, "raw_text": raw,
            "method": method, "warnings": warnings, "confidence": .94 if not warnings else .55}


def ruled_rows(page) -> tuple[list[dict], list[dict]]:
    rows, tables = [], []
    finder = page.find_tables()
    for table in finder.tables[:80]:
        extracted = table.extract()
        mapping = {}
        for index, cells in enumerate(extracted[:2000]):
            header = {col: field_name(value or "") for col, value in enumerate(cells)}
            if {"position", "part_number", "description"}.issubset(set(header.values())):
                mapping = {col: name for col, name in header.items() if name}
                continue
            if not mapping:
                continue
            values = {name: (cells[col] or "").strip() for col, name in mapping.items() if col < len(cells)}
            bbox = list(table.rows[index].bbox)
            row = make_row(values, bbox, " | ".join(value or "" for value in cells), method="NATIVE_TABLE")
            if row:
                rows.append(row)
        if mapping:
            tables.append({"bbox": list(table.bbox), "columns": list(mapping.values()), "method": "NATIVE_TABLE"})
    return rows, tables


def word_lines(words: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for word in sorted(words, key=lambda word: (word["bbox"][1], word["bbox"][0])):
        # Layout grouping is independent of PDF content-stream block order.
        line = next((line for line in reversed(lines[-4:]) if abs(line[0]["bbox"][1] - word["bbox"][1]) <= 3), None)
        if line is None:
            lines.append([word])
        else:
            line.append(word)
    return [sorted(line, key=lambda word: word["bbox"][0]) for line in lines]


def layout_rows(words: list[dict], width: float) -> tuple[list[dict], list[dict]]:
    rows, tables = [], []
    columns: list[tuple[float, str]] = []
    previous = None
    for line in word_lines(words):
        anchors = []
        used = set()
        # Longest synonym wins: "Part No." must not become a position column.
        for length in (3, 2, 1):
            for index in range(len(line) - length + 1):
                if set(range(index, index + length)) & used:
                    continue
                name = field_name(" ".join(word["text"] for word in line[index:index + length]))
                if name:
                    anchors.append((line[index]["bbox"][0], name))
                    used.update(range(index, index + length))
        if {"position", "part_number", "description"}.issubset({name for _, name in anchors}):
            columns = sorted(anchors)
            tables.append({"bbox": [line[0]["bbox"][0], line[0]["bbox"][1], width, line[-1]["bbox"][3]],
                           "columns": [name for _, name in columns], "method": "WORD_LAYOUT"})
            previous = None
            continue
        if not columns:
            continue
        # A repeated position header starts another independent column table.
        starts = [i for i, (_, name) in enumerate(columns) if name == "position"]
        for segment, start in enumerate(starts):
            end = starts[segment + 1] if segment + 1 < len(starts) else len(columns)
            selected = columns[start:end]
            right = columns[end][0] - 6 if end < len(columns) else width
            left = selected[0][0] - 6
            region = [word for word in line if left <= word["bbox"][0] < right]
            if not region:
                continue
            values: dict[str, str] = {}
            for word in region:
                name = selected[0][1]
                for x, field in selected:
                    if word["bbox"][0] >= x - 6:
                        name = field
                values[name] = (values.get(name, "") + " " + word["text"]).strip()
            bbox = [min(w["bbox"][0] for w in region), min(w["bbox"][1] for w in region),
                    max(w["bbox"][2] for w in region), max(w["bbox"][3] for w in region)]
            row = make_row(values, bbox, " ".join(w["text"] for w in region), method="WORD_LAYOUT")
            if row:
                rows.append(row)
                previous = row
            elif (previous and len(starts) == 1 and set(values) == {"description"}
                  and -3 <= bbox[1] - previous["bbox"][3] <= 12):
                # Only a close, description-only continuation can inherit a row identity.
                previous["payload"]["description"] = (previous["payload"]["description"] or "") + "\n" + values["description"]
                previous["raw_values"]["description"] = previous["payload"]["description"]
                previous["raw_text"] += "\n" + " ".join(w["text"] for w in region)
                previous["bbox"][3] = bbox[3]
            else:
                previous = None
    return rows, tables
