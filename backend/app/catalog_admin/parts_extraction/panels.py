"""Local panel schemas: repeated identities separate panels, languages do not.

No values, absolute coordinates, manufacturer or document controls are borrowed.
The existing bounded schema scorer still decides whether each panel is resolved.
"""

from .columns import header_geometry
from .schema import header_candidates, infer_schema


def regions(headers):
    hints = [header_candidates(header) for header in headers]
    # Item may denote a position only when there is no stronger position label;
    # the unchanged content scorer must still resolve that local interpretation.
    position_hint = 1.5 if any(h.get("position", 0) >= 1.5 for h in hints) else 1.3
    starts = [i for i, hint in enumerate(hints) if hint.get("position", 0) >= position_hint]
    if len(starts) < 2:
        return [(0, len(headers))]
    # Partition by repeated local semantic roles, not an assumed first column
    # or panel width. Multiple equally valid cuts remain unresolved.
    from functools import lru_cache
    def valid(start, end):
        local = hints[start:end]
        return (3 <= end - start <= 12
            and sum(h.get("position", 0) >= position_hint for h in local) == 1
            and sum(h.get("part_number", 0) >= 1 for h in local) == 1
            and sum(h.get("quantity", 0) >= 1 for h in local) == 1
            and any(h.get("description", 0) >= 1 for h in local))
    @lru_cache(maxsize=64)
    def partitions(start):
        if start == len(headers):
            return [()]
        solutions = []
        for end in range(start + 3, min(len(headers), start + 12) + 1):
            if valid(start, end):
                for tail in partitions(end):
                    solutions.append(((start, end), *tail))
                    if len(solutions) == 2:
                        return solutions
        return solutions
    choices = partitions(0) if len(headers) <= 32 else []
    if len(choices) == 1 and len(choices[0]) == len(starts):
        return list(choices[0])
    return [(0, len(headers))]


def parse(headers, cells, boxes, bbox, boundaries, *, method="NATIVE_TABLE"):
    from .tables import parse_region

    result, tables = [], []
    groups = regions(headers)
    for panel, (start, end) in enumerate(groups):
        local_headers = headers[start:end]
        local_cells = [row[start:end] for row in cells]
        hints = [header_candidates(header) for header in local_headers]
        descriptions = [i for i, hint in enumerate(hints) if set(hint) == {"description"}]
        # Separate language columns retain every original cell. Only their first
        # physical description competes for the primary description role.
        omitted = set(descriptions[1:])
        selected = [i for i in range(len(local_headers)) if i not in omitted]
        schema = infer_schema([local_headers[i] for i in selected],
            [[row[i] for i in selected] for row in local_cells])
        mapping = {str(i): "unknown" for i in range(len(local_headers))}
        mapping.update({str(selected[int(i)]): role for i, role in schema["mapping"].items()})
        schema = {**schema, "mapping": mapping, "method": "LOCAL_PANEL_SCHEMA",
            "description_columns": descriptions, "projected_columns": selected}
        local_box = [boundaries[start], bbox[1], boundaries[end], bbox[3]]
        row_boxes = [[boundaries[start], box[1], boundaries[end], box[3]] for box in boxes]
        rows, table = parse_region(local_headers, local_cells, row_boxes, local_box, method,
            mapping=mapping if schema["state"] == "RESOLVED" else None)
        if schema["state"] != "RESOLVED":
            rows = []
        table["schema"] = schema
        table["panel"] = {"index": panel, "column_start": start, "column_end": end,
            "parent_bbox": bbox, "count": len(groups)}
        table["geometry"] = {"state": "RESOLVED", "warnings": [],
            "boundaries": boundaries[start:end + 1]}
        table["header_geometry"] = [header_geometry(header, [{"bbox": [left, bbox[1], right,
            boxes[0][1] if boxes else bbox[1]]}]) for header, left, right in zip(
                local_headers, boundaries[start:end], boundaries[start + 1:end + 1], strict=True)]
        for row in rows:
            row["schema"] = {"headers": local_headers, "mapping": mapping, "score": schema["score"]}
            row["warnings"].extend(schema["warnings"])
            if schema["warnings"]:
                row["confidence"] = min(row["confidence"], .7)
            # Line wrapping is layout, not a new description character. Keep
            # the verbatim cell and line breaks in raw_values/raw_cells evidence.
            for role in ("description", "technical_specification", "technical_notes", "quantity_raw"):
                if row["payload"].get(role):
                    row["payload"][role] = row["payload"][role].replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
            row["panel"] = table["panel"]
            row["original_descriptions"] = [{"column": i, "header": local_headers[i],
                "value": row["raw_cells"][i]} for i in descriptions]
        result.extend(rows)
        tables.append(table)
    return result, tables
