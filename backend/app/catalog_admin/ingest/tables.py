"""Geometry first, contextual schemas second, exact source rows throughout."""

from .schema import header_candidates, infer_schema
from .values import PLACEHOLDERS, POSITION, quantity


def make_row(values: dict, bbox: list[float], raw: str, *, method: str) -> dict | None:
    position = values.get("position", "").strip()
    uncertain_position = not POSITION.fullmatch(position)
    if uncertain_position and not (position in PLACEHOLDERS and values.get("part_number", "") not in PLACEHOLDERS
                                  and values.get("description")):
        return None
    if not any(values.get(key, "") not in PLACEHOLDERS for key in ("part_number", "description")):
        return None
    warnings = ["MISSING_POSITION"] if uncertain_position else []
    if any(len(value) > (80 if key == "position" else 120 if key in {"part_number", "quantity"} else 4000)
           for key, value in values.items()):
        warnings.append("FIELD_TOO_LONG")
    if values.get("part_number", "").strip() in PLACEHOLDERS:
        warnings.append("MISSING_PART_NUMBER")
    if values.get("description", "").strip() in PLACEHOLDERS:
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


def parse_region(headers: list[str], cells: list[list[str]], boxes: list[list[float]], bbox: list[float],
                 method: str, anchors: list[float] | None = None) -> tuple[list[dict], dict]:
    schema = infer_schema(headers, cells)
    table = {"bbox": bbox, "headers": headers, "columns": list(schema["mapping"].values()),
             "schema": schema, "method": method, "sample_cells": cells[:8],
             "row_count": len(cells), "anchors": anchors or [],
             "bom_evidence": sum(bool(header_candidates(header)) for header in headers) >= 2}
    rows, previous = [], None
    for raw_cells, box in zip(cells, boxes, strict=True):
        if schema["state"] != "RESOLVED":
            break
        values = {role: raw_cells[int(col)] if int(col) < len(raw_cells) else ""
                  for col, role in schema["mapping"].items() if role != "unknown"}
        if sum(bool(header_candidates(value)) for value in raw_cells) >= 3:
            previous = None
            continue
        raw = " | ".join(raw_cells) if method == "NATIVE_TABLE" else " ".join(value for value in raw_cells if value)
        row = make_row(values, box, raw, method=method)
        if row:
            row["schema"] = {"headers": headers, "mapping": schema["mapping"], "score": schema["score"]}
            row["raw_cells"] = raw_cells
            row["warnings"].extend(schema["warnings"])
            if schema["warnings"]:
                row["confidence"] = min(row["confidence"], .7)
            rows.append(row)
            previous = row
        elif (previous and values.get("description") and not any(values.get(key) for key in ("position", "part_number", "quantity"))
              and -3 <= box[1] - previous["bbox"][3] <= 12):
            for key in ("description", "technical_notes", "technical_specification"):
                if values.get(key):
                    previous["payload"][key] = (previous["payload"].get(key) or "") + "\n" + values[key]
                    previous["raw_values"][key] = previous["payload"][key]
            previous["raw_text"] += "\n" + (" | ".join(raw_cells) if method == "NATIVE_TABLE" else " ".join(value for value in raw_cells if value))
            previous.setdefault("continuation_cells", []).append(raw_cells)
            previous["bbox"][3] = box[3]
        else:
            previous = None
    return rows, table


def ruled_rows(page) -> tuple[list[dict], list[dict]]:
    rows, tables = [], []
    for table in page.find_tables().tables[:80]:
        extracted = [[str(value or "").strip() for value in row] for row in table.extract()[:2000]]
        if not extracted:
            continue
        headers = table.header.names if table.header.external else extracted[0]
        offset = 0 if table.header.external else 1
        parts, region = parse_region([str(value or "") for value in headers], extracted[offset:],
            [list(row.bbox) for row in table.rows[offset:offset + len(extracted) - offset]], list(table.bbox), "NATIVE_TABLE")
        rows.extend(parts)
        tables.append(region)
    return rows, tables


def word_lines(words: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for word in sorted(words, key=lambda word: (word["bbox"][1], word["bbox"][0])):
        line = next((line for line in reversed(lines[-4:]) if abs(line[0]["bbox"][1] - word["bbox"][1]) <= 3), None)
        if line is None:
            lines.append([word])
        else:
            line.append(word)
    return [sorted(line, key=lambda word: word["bbox"][0]) for line in lines]


def header_anchors(line: list[dict]) -> list[tuple[float, str]]:
    anchors, used = [], set()
    for length in (3, 2, 1):
        for index in range(len(line) - length + 1):
            if set(range(index, index + length)) & used:
                continue
            selected = line[index:index + length]
            if any(selected[i + 1]["bbox"][0] - selected[i]["bbox"][2] > 16 for i in range(length - 1)):
                continue
            text = " ".join(word["text"] for word in selected)
            if header_candidates(text):
                anchors.append((selected[0]["bbox"][0], text))
                used.update(range(index, index + length))
    for index, word in enumerate(line):
        if index not in used:
            anchors.append((word["bbox"][0], word["text"]))
    return sorted(anchors)


def layout_rows(words: list[dict], width: float, *, continuation: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    rows, tables, regions = [], [], []
    lines = word_lines(words)
    for index, line in enumerate(lines):
        anchors = header_anchors(line)
        recognized = [header_candidates(header) for _, header in anchors]
        known = sum(bool(hints) for hints in recognized)
        strong = sum(max(hints.values(), default=0) >= 2 for hints in recognized)
        recognized_header = len(anchors) >= 3 and known >= 2 and known / len(anchors) >= .5 and (known >= 3 or strong)
        # Borderless unknown headers still have independent, repeated alignment.
        geometric_header = (3 <= len(anchors) <= 12 and not any(POSITION.fullmatch(text) for _, text in anchors)
            and all(anchors[i + 1][0] - anchors[i][0] >= 30 for i in range(len(anchors) - 1))
            and len(lines[index + 1:index + 3]) == 2
            and all(sum(any(abs(word["bbox"][0] - x) <= 8 for word in following) for x, _ in anchors) >= 3
                    for following in lines[index + 1:index + 3]))
        if recognized_header or geometric_header:
            pn = [i for i, hints in enumerate(recognized) if hints.get("part_number", 0) >= 2]
            starts = [0] + [max(1, col - 1) for col in pn[1:]]
            for segment, start in enumerate(starts):
                end = starts[segment + 1] if segment + 1 < len(starts) else len(anchors)
                if end - start >= 3:
                    regions.append({"line": index, "anchors": anchors[start:end],
                                    "right": anchors[end][0] - 6 if end < len(anchors) else width})
    if not regions and continuation:
        for old in continuation[:4]:
            if old.get("schema", {}).get("state") == "RESOLVED" and old.get("anchors"):
                regions.append({"line": -1, "anchors": list(zip(old["anchors"], old["headers"], strict=True)),
                                "right": min(width, old["bbox"][2] + 10), "inferred": True})
    for region in regions[:80]:
        anchors = region["anchors"]
        first, right = anchors[0][0] - 6, region["right"]
        next_header = min((r["line"] for r in regions if r["line"] > region["line"]), default=len(lines))
        cells, boxes = [], []
        for line in lines[region["line"] + 1:next_header]:
            selected = [word for word in line if first <= word["bbox"][0] < right]
            if not selected:
                continue
            values = [""] * len(anchors)
            for word in selected:
                col = max((i for i, (x, _) in enumerate(anchors) if word["bbox"][0] >= x - 6), default=0)
                values[col] = (values[col] + " " + word["text"]).strip()
            if region.get("inferred") and not POSITION.fullmatch(values[0]) and not cells:
                continue
            box = [min(w["bbox"][0] for w in selected), min(w["bbox"][1] for w in selected),
                   max(w["bbox"][2] for w in selected), max(w["bbox"][3] for w in selected)]
            if boxes and box[1] - boxes[-1][3] > 65:
                break
            cells.append(values)
            boxes.append(box)
            if len(cells) >= 2000:
                break
        if not cells:
            continue
        top = lines[region["line"]][0]["bbox"][1] if region["line"] >= 0 else boxes[0][1]
        box = [first, top, max(box[2] for box in boxes), max(box[3] for box in boxes)]
        parts, table = parse_region([text for _, text in anchors], cells, boxes, box, "WORD_LAYOUT", [x for x, _ in anchors])
        if region.get("inferred"):
            table["continuation_inferred"] = True
            for part in parts:
                part["warnings"].append("CONTINUATION_INFERRED")
                part["confidence"] = min(part["confidence"], .7)
        rows.extend(parts)
        tables.append(table)
    return rows, tables
