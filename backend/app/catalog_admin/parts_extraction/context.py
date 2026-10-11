"""Semantic-only group profiles; coordinates and cell values never migrate."""

from .schema import header_candidates
from .tables import parse_region, word_lines
from .values import PLACEHOLDERS, POSITION, quantity


def widths(table):
    bounds = table.get("geometry", {}).get("normalized_boundaries") or []
    span = bounds[-1] - bounds[0] if bounds else 0
    return [(b - a) / span for a, b in zip(bounds, bounds[1:])] if span > 0 else []


def profiles(evidence, sha256):
    return [{"sha256": sha256, "headers": table["headers"], "mapping": table["schema"]["mapping"],
             "width_ratios": widths(table)} for table in evidence.get("tables", [])[:80]
        if table.get("quality", {}).get("state") == "COMPLETE_CANDIDATES"
        and table.get("bom_evidence") and not table.get("continuation_inferred")
        and table.get("schema", {}).get("state") == "RESOLVED"]


def compatible(table, profile, sha256):
    headers, mapping = table["headers"], profile["mapping"]
    if len(headers) != len(profile["headers"]) or set(mapping) != {str(i) for i in range(len(headers))}:
        return False
    if not {"position", "part_number", "description", "quantity"} <= set(mapping.values()):
        return False
    hints = [header_candidates(header) for header in headers]
    agreement = sum(bool(hint) and mapping[str(i)] in hint for i, hint in enumerate(hints))
    if any(hint and mapping[str(i)] not in hint for i, hint in enumerate(hints)):
        return False
    same = profile["sha256"] == sha256
    # A foreign PDF must supply local semantic evidence. Headerless cross-PDF
    # borrowing is deliberately rejected even when the shapes happen to match.
    if not same and agreement < 2:
        return False
    local, prior = widths(table), profile.get("width_ratios", [])
    if same and agreement < 2 and (len(local) != len(prior) or not local
        or any(abs(a - b) > .12 for a, b in zip(local, prior, strict=True))):
        return False
    cells = table.get("cells", [])[:32]
    if not cells:
        return False
    tests = {"position": lambda v: bool(POSITION.fullmatch(v)),
        "part_number": lambda v: v not in PLACEHOLDERS and any(c.isdigit() for c in v) and not any(c.isspace() for c in v),
        "description": lambda v: v not in PLACEHOLDERS and any(c.isalpha() for c in v),
        "quantity": lambda v: quantity(v) is not None}
    for role, check in tests.items():
        col = next(int(i) for i, value in mapping.items() if value == role)
        if sum(col < len(row) and check(row[col]) for row in cells) / len(cells) < .6:
            return False
    return True


def resolve(rows, tables, config):
    result = list(rows)
    for index, table in enumerate(tables):
        if table["schema"]["state"] == "RESOLVED":
            continue
        matches = [profile for profile in config.get("context_profiles", [])[:32]
                   if compatible(table, profile, config.get("source_sha256"))]
        mappings = {tuple(sorted(profile["mapping"].items())) for profile in matches}
        if len(mappings) != 1:
            continue
        profile = matches[0]
        inferred, updated = parse_region(table["headers"], table["cells"], table["row_boxes"], table["bbox"],
            table["method"], mapping=profile["mapping"])
        updated = {**table, **updated, "context": {"sha256": profile["sha256"],
            "headers": profile["headers"], "attempt_id": profile.get("attempt_id"),
            "evidence_digest": profile.get("evidence_digest"), "method": "SEMANTIC_GROUP_PROFILE"}, "continuation_inferred": True}
        updated["schema"]["method"] = "SEMANTIC_GROUP_PROFILE"
        for row in inferred:
            row["warnings"].append("CONTEXT_SCHEMA_INFERRED")
            row["confidence"] = min(row["confidence"], .7)
        tables[index] = updated
        result.extend(inferred)
    return result, tables


def borderless(words, width, config):
    """Headerless local whitespace geometry; a profile supplies roles only."""
    available = [profile for profile in config.get("context_profiles", [])[:32]
                 if profile["sha256"] == config.get("source_sha256")]
    lines = word_lines(words)
    for profile in available:
        count = len(profile["headers"])
        cells, boxes, segments = [], [], []
        for line in lines:
            chunks = []
            for word in line:
                if not chunks or word["bbox"][0] - chunks[-1][-1]["bbox"][2] > max(16, (word["bbox"][3] - word["bbox"][1]) * 1.4):
                    chunks.append([word])
                else:
                    chunks[-1].append(word)
            if len(chunks) != count:
                continue
            cells.append([" ".join(w["text"] for w in chunk) for chunk in chunks])
            boxes.append([line[0]["bbox"][0], min(w["bbox"][1] for w in line), line[-1]["bbox"][2], max(w["bbox"][3] for w in line)])
            segments.append(chunks)
        if not cells:
            continue
        # Local column whitespace must persist across all selected lines.
        bounds = [min(box[0] for box in boxes)]
        for col in range(count - 1):
            left = max(chunks[col][-1]["bbox"][2] for chunks in segments)
            right = min(chunks[col + 1][0]["bbox"][0] for chunks in segments)
            if left >= right:
                break
            bounds.append((left + right) / 2)
        bounds.append(max(box[2] for box in boxes))
        if len(bounds) != count + 1:
            continue
        _, table = parse_region([""] * count, cells, boxes, [bounds[0], boxes[0][1], bounds[-1], boxes[-1][3]], "WORD_LAYOUT")
        table["schema"]["state"] = "NEEDS_REVIEW"
        table.update({"page_width": width, "geometry": {"state": "RESOLVED", "warnings": [],
            "normalized_boundaries": [b / width for b in bounds]}})
        rows, tables = resolve([], [table], config)
        if rows:
            return rows, tables
    return [], []
