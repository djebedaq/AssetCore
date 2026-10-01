"""Geometry first, contextual schemas second, exact source rows throughout."""

from .columns import assign_words, header_geometry, infer_columns
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


def header_anchors(line: list[dict]) -> list[dict]:
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
                anchors.append(header_geometry(text, selected))
                used.update(range(index, index + length))
    pending = []
    for index, word in enumerate(line):
        if index in used:
            if pending:
                anchors.append(header_geometry(" ".join(w["text"] for w in pending), pending))
                pending = []
            continue
        if pending and word["bbox"][0] - pending[-1]["bbox"][2] > max(4, word["bbox"][3] - word["bbox"][1]):
            anchors.append(header_geometry(" ".join(w["text"] for w in pending), pending))
            pending = []
        pending.append(word)
    if pending:
        anchors.append(header_geometry(" ".join(w["text"] for w in pending), pending))
    return sorted(anchors, key=lambda item: item["center"])


def layout_rows(words: list[dict], width: float, *, continuation: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    rows, tables, regions = [], [], []
    lines = word_lines(words)
    for index, line in enumerate(lines):
        headers = header_anchors(line)
        if not 3 <= len(headers) <= 24:
            continue
        recognized = [header_candidates(header["text"]) for header in headers]
        known = sum(bool(hints) for hints in recognized)
        strong = sum(max(hints.values(), default=0) >= 2 for hints in recognized)
        recognized_header = known >= 2 and known / len(headers) >= .5 and (known >= 3 or strong)
        geometric_header = (not any(POSITION.fullmatch(h["text"]) for h in headers)
            and len(lines[index + 1:index + 3]) == 2)
        if not recognized_header and not geometric_header:
            continue
        pn = [i for i, hints in enumerate(recognized) if hints.get("part_number", 0) >= 2]
        starts = [0] + [max(1, col - 1) for col in pn[1:]]
        for segment, start in enumerate(starts):
            end = starts[segment + 1] if segment + 1 < len(starts) else len(headers)
            selected = headers[start:end]
            if not 3 <= len(selected) <= 12:
                continue
            centers = [h["center"] for h in selected]
            left = (headers[start - 1]["center"] + centers[0]) / 2 if start else max(0, centers[0] - .55 * (centers[1] - centers[0]))
            right = (centers[-1] + headers[end]["center"]) / 2 if end < len(headers) else min(width, centers[-1] + .55 * (centers[-1] - centers[-2]))
            if not recognized_header:
                trial = infer_columns(selected, lines[index + 1:index + 3], left, right, width)
                if trial.get("coherence", 0) < .8 or trial.get("populated_rows", 0) < 2:
                    continue
            regions.append({"line": index, "headers": selected, "left": left, "right": right})
    if not regions and continuation:
        for old in continuation[:4]:
            bounds = old.get("geometry", {}).get("normalized_boundaries")
            if old.get("schema", {}).get("state") != "RESOLVED" or not bounds:
                continue  # Legacy geometry is deliberately re-extracted, never reinterpreted.
            scale = width / old["page_width"]
            headers = [{**h, "x0": h["x0"] * scale, "x1": h["x1"] * scale,
                "center": h["center"] * scale, "width": h["width"] * scale,
                "bbox": [h["bbox"][0] * scale, h["bbox"][1], h["bbox"][2] * scale, h["bbox"][3]]}
                for h in old["header_geometry"]]
            regions.append({"line": -1, "headers": headers, "left": bounds[0] * width, "right": bounds[-1] * width,
                            "inferred": True, "stored_boundaries": [b * width for b in bounds]})
    for region in regions[:80]:
        headers = region["headers"]
        next_header = min((r["line"] for r in regions if r["line"] > region["line"]), default=len(lines))
        selected_lines = []
        for line in lines[region["line"] + 1:next_header]:
            selected = [w for w in line if region["left"] <= (w["bbox"][0] + w["bbox"][2]) / 2 <= region["right"]]
            if not selected:
                continue
            if selected_lines and selected[0]["bbox"][1] - max(w["bbox"][3] for w in selected_lines[-1]) > 65:
                break
            selected_lines.append(selected)
            if len(selected_lines) >= 2000:
                break
        if not selected_lines:
            continue
        if region.get("stored_boundaries"):
            boundaries = region["stored_boundaries"]
            geometry = {"boundaries": boundaries, "normalized_boundaries": [b / width for b in boundaries],
                        "state": "RESOLVED", "alternatives": [], "warnings": [], "reused": True}
        else:
            geometry = infer_columns(headers, selected_lines, region["left"], region["right"], width)
            boundaries = geometry["boundaries"]
        if not boundaries:
            continue
        cells, boxes, assignments, conflicts = [], [], [], []
        for line in selected_lines:
            values, assigned, conflict = assign_words(line, boundaries)
            if not assigned:
                continue
            if region.get("inferred") and sum(bool(value) for value in values) < 3 and not cells:
                continue
            cells.append(values)
            assignments.append(assigned)
            conflicts.append(conflict)
            boxes.append([min(w["bbox"][0] for w in assigned), min(w["bbox"][1] for w in assigned),
                          max(w["bbox"][2] for w in assigned), max(w["bbox"][3] for w in assigned)])
        if not cells:
            continue
        top = lines[region["line"]][0]["bbox"][1] if region["line"] >= 0 else boxes[0][1]
        bbox = [boundaries[0], top, boundaries[-1], max(box[3] for box in boxes)]
        parts, table = parse_region([h["text"] for h in headers], cells, boxes, bbox, "WORD_LAYOUT", [h["x0"] for h in headers])
        table.update({"header_geometry": headers, "geometry": geometry, "page_width": width,
                      "sample_assignments": assignments[:5]})
        warnings = list(geometry["warnings"])
        if any(conflicts) and "GEOMETRY_AMBIGUOUS" not in warnings:
            warnings.append("GEOMETRY_AMBIGUOUS")
            geometry["warnings"] = warnings
            geometry["state"] = "NEEDS_REVIEW"
        if region.get("inferred"):
            table["continuation_inferred"] = True
            warnings.append("CONTINUATION_INFERRED")
        for part in parts:
            part["column_geometry"] = {"table_bbox": bbox, "header_geometry": headers,
                "normalized_boundaries": geometry["normalized_boundaries"], "state": geometry["state"]}
            part["warnings"].extend(warnings)
            if warnings:
                part["confidence"] = min(part["confidence"], .55 if "GEOMETRY_AMBIGUOUS" in warnings else .7)
        rows.extend(parts)
        tables.append(table)
    return rows, tables
