"""Observable coverage and competing strategies, never an OCR truth score."""

import copy
import json
from collections import Counter

import fitz

from .tables import document_metadata


def assessment(rows, table):
    excluded = table.get("excluded_rows", [])
    observed = table.get("row_count", 0) - len(excluded)
    covered = {index for row in rows for index in row.get("source_row_indices", [row.get("source_row_index")])}
    covered.discard(None)
    invalid = [row for row in rows if any(w in row["warnings"] for w in
        ("MISSING_POSITION", "MISSING_PART_NUMBER", "MISSING_DESCRIPTION", "QUANTITY_UNCERTAIN", "FIELD_TOO_LONG",
         "IDENTIFIER_MIXED_SCRIPTS", "IDENTIFIER_SPACING", "UNREADABLE_IDENTIFIER", "QUANTITY_IMPLAUSIBLE",
         "OCR_READ_DISAGREEMENT", "STRATEGY_DISAGREEMENT"))]
    semantic = table.get("schema", {}).get("state") == "RESOLVED" and bool(rows)
    missing = max(0, observed - len(covered))
    ruled = table.get("method") in {"NATIVE_TABLE", "IMAGE_CELL_OCR"}
    warnings = []
    if missing:
        warnings.append("ROW_COVERAGE_INCOMPLETE")
    if not semantic:
        warnings.append("COLUMNS_UNRESOLVED")
    if invalid:
        warnings.append("PARTIAL_CELLS")
    if not ruled and rows:
        warnings.append("BORDERLESS_COVERAGE_UNCERTAIN")
    warnings.extend(table.get("strategy_warnings", []))
    complete = (semantic and not missing and not invalid and not table.get("incomplete_regions")
        and table.get("geometry", {}).get("state") != "NEEDS_REVIEW")
    return {"state": "COMPLETE_CANDIDATES" if complete else "NEEDS_REVIEW", "basis": "PHYSICAL_ROW_BANDS" if ruled else "TEXT_LINE_REGIONS",
        "observed_rows": observed, "candidate_rows": len(rows), "covered_rows": len(covered), "missing_rows": missing,
        "partial_rows": len(invalid), "warnings": warnings,
        # Rank by semantic validity, field quality and coverage, not raw row count.
        # A local physical-cell schema preserves wrapped/empty cells. A word
        # reader can look cleaner precisely because it omitted their second line.
        "rank": [int(semantic), int(ruled and bool(table.get("panel"))
                 and table.get("geometry", {}).get("state") == "RESOLVED"),
                 (len(rows) - len(invalid)) / max(1, len(rows)),
                 len(covered) / max(1, observed), int(ruled), int(complete)]}


def overlap(a, b):
    left, right = fitz.Rect(a), fitz.Rect(b)
    return (left & right).get_area() / max(1, min(left.get_area(), right.get_area()))


def physical_coverage(rows, tables, proposals, result):
    """Independent ruled bands still count when their columns are unreadable."""
    bands, owners, truncated = [], [], False
    for _, _, proposed in proposals:
        for table in proposed:
            if table["method"] not in {"NATIVE_TABLE", "IMAGE_CELL_OCR"} or not (table.get("bom_evidence") or table.get("grid")):
                continue
            excluded = {item.get("index") for item in table.get("excluded_rows", [])}
            for index, box in enumerate(table.get("row_boxes", [])):
                if index in excluded or document_metadata(table["cells"][index]):
                    continue
                if len(bands) >= 2000:
                    truncated = True
                    break
                if any(overlap(box, old) > .8 for old in bands):
                    continue
                bands.append(box)
                owners.append(table)
    if not bands:
        return
    covered = set()
    for row in rows:
        box = row["bbox"]
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        matches = [(overlap(box, band), i) for i, band in enumerate(bands)
                   if band[0] <= cx <= band[2] and band[1] <= cy <= band[3]]
        if matches:
            score, index = max(matches)
            if score > .5:
                covered.add(index)  # One candidate cannot conceal two bands.
    missing = set(range(len(bands))) - covered
    for index in missing:
        table = owners[index]
        if table["schema"]["state"] == "RESOLVED" or any(
                old["method"] == table["method"] and old["bbox"] == table["bbox"] for old in tables):
            continue
        extra = copy.deepcopy(table)
        extra["table_index"], extra["quality"] = len(tables), assessment([], extra)
        tables.append(extra)  # Keep a working column-mapping path and raw cells.
    outside = [table for table in tables if not any(overlap(table["bbox"], owner["bbox"]) > .6 for owner in owners)]
    result.update({"observed_rows": len(bands) + sum(t["quality"]["observed_rows"] for t in outside),
        "missing_rows": len(missing) + sum(t["quality"]["missing_rows"] for t in outside),
        "basis": "MIXED_PHYSICAL_AND_TEXT_REGIONS" if outside else "PHYSICAL_ROW_BANDS",
        "physical_coverage": {"observed_rows": len(bands), "covered_rows": len(covered),
            "missing_rows": len(missing), "truncated": truncated},
        "needs_context": result["needs_context"] or any(t["schema"]["state"] != "RESOLVED" for t in tables)})
    if missing or truncated:
        result["state"] = "NEEDS_REVIEW"
        result["warnings"] = ["ROW_COVERAGE_INCOMPLETE"]


def choose(strategies):
    # Keep independent proposals immutable across selection passes. Comparison
    # annotations must not feed back into the next strategy's quality score.
    strategies = copy.deepcopy(strategies)
    selected, summaries = [], []
    for name, rows, tables in strategies:
        for table in tables:
            if not table.get("cells") and not table.get("bom_evidence") and not table.get("grid"):
                summaries.append({"strategy": name, "bbox": table["bbox"], "rejected": "EMPTY_NON_BOM"})
                continue
            if "excluded_rows" in table:
                table["excluded_rows"] = [e for e in table["excluded_rows"] if e["reason"] != "DUPLICATE_REGION"]
            if table.get("cells") and all(document_metadata(cells) for cells in table["cells"]) and not table.get("bom_evidence"):
                summaries.append({"strategy": name, "bbox": table["bbox"], "rejected": "DOCUMENT_METADATA"})
                continue
            members = [row for row in rows if overlap(row["bbox"], table["bbox"]) > .9]
            quality = assessment(members, table)
            table["quality"] = quality
            summaries.append({"strategy": name, "bbox": table["bbox"], **quality})
            matching = next((old for old in selected if overlap(old["table"]["bbox"], table["bbox"]) > .6), None)
            candidate = {"table": table, "rows": members, "quality": quality, "strategy": name}
            if matching:
                old_payloads = [row["payload"] for row in matching["rows"]]
                new_payloads = [row["payload"] for row in members]
                disagreement = old_payloads != new_payloads and bool(old_payloads and new_payloads)
                competing = matching
                if quality["rank"] > matching["quality"]["rank"]:
                    selected.remove(matching)
                    selected.append(candidate)
                else:
                    competing = candidate
                    candidate = matching
                if disagreement:
                    candidate["table"].setdefault("strategy_warnings", []).append("STRATEGY_DISAGREEMENT")
                    # A cleaner reading may omit unreadable physical rows.
                    # Keep their proposal too; spatial de-duplication below
                    # removes repeated readings, never unseen partial bands.
                    if any(not any(overlap(row["bbox"], kept["bbox"]) > .8 for kept in candidate["rows"])
                           for row in competing["rows"]):
                        competing["table"].setdefault("strategy_warnings", []).append("STRATEGY_DISAGREEMENT")
                        selected.append(competing)
                    alternative = {"strategy": competing["strategy"], "rows": [{"payload": row["payload"],
                        "bbox": row["bbox"], "raw_cells": row.get("raw_cells"), "warnings": row["warnings"]}
                        for row in competing["rows"][:200]], "truncated": len(competing["rows"]) > 200}
                    readings = candidate["table"].setdefault("competing_readings", [])
                    if alternative not in readings and len(readings) < 4:
                        readings.append(alternative)
            else:
                selected.append(candidate)
    # A broad layout proposal can overlap several smaller ruled tables. Count
    # the same physical reading once, while retaining competing values for review.
    physical = []
    for item in sorted(selected, key=lambda i: assessment(i["rows"], i["table"])["rank"], reverse=True):
        retained = []
        for row in item["rows"]:
            matches = [old for old in physical if overlap(old["bbox"], row["bbox"]) > .8]
            if any(old["payload"] == row["payload"] for old in matches):
                for index in row.get("source_row_indices", [row.get("source_row_index")]):
                    excluded = {"index": index, "reason": "DUPLICATE_REGION", "bbox": row["bbox"]}
                    if excluded not in item["table"].setdefault("excluded_rows", []):
                        item["table"]["excluded_rows"].append(excluded)
                continue
            for old in matches:
                old["warnings"] = sorted(set(old["warnings"] + ["STRATEGY_DISAGREEMENT"]))
                row["warnings"] = sorted(set(row["warnings"] + ["STRATEGY_DISAGREEMENT"]))
                old["reconciliation_required"] = row["reconciliation_required"] = True
            retained.append(row)
            physical.append(row)
        item["rows"] = retained
    selected = [item for item in selected if item["rows"] or not item["table"].get("excluded_rows")]
    selected.sort(key=lambda item: (item["table"]["bbox"][1], item["table"]["bbox"][0]))
    rows, tables = [], []
    for ordinal, item in enumerate(selected):
        table = item["table"]
        table["table_index"] = ordinal
        rows.extend(item["rows"])
        for row in item["rows"]:
            row["table_index"] = ordinal
            row["source_region"] = {"table": ordinal, "row": row.get("source_row_index"), "bbox": row["bbox"]}
            row["warnings"] = sorted(set(row["warnings"] + table.get("strategy_warnings", [])))
            if table.get("strategy_warnings"):
                row["confidence"] = min(row["confidence"], .7)
        table["quality"] = assessment(item["rows"], table)
        tables.append(table)
    # Equal visible values are distinct occurrences. Geometry is evidence, not
    # identity; ordinal disambiguation is needed only for these equal payloads.
    counts = Counter(json.dumps(row["payload"], sort_keys=True) for row in rows)
    for row in rows:
        if counts[json.dumps(row["payload"], sort_keys=True)] > 1:
            row["occurrence_key"] = [row["table_index"], row.get("source_row_index")]
    quality = {"state": "COMPLETE_CANDIDATES" if tables and all(t["quality"]["state"] == "COMPLETE_CANDIDATES" for t in tables) else "NEEDS_REVIEW",
        "basis": "PHYSICAL_ROW_BANDS" if tables and all(t["quality"]["basis"] == "PHYSICAL_ROW_BANDS" for t in tables) else "TEXT_LINE_REGIONS",
        "observed_rows": sum(t["quality"]["observed_rows"] for t in tables),
        "candidate_rows": len(rows), "missing_rows": sum(t["quality"]["missing_rows"] for t in tables),
        "partial_rows": sum(t["quality"]["partial_rows"] for t in tables),
        "needs_context": not rows or any(t["schema"]["state"] != "RESOLVED" for t in tables)}
    physical_coverage(rows, tables, strategies, quality)
    return rows, tables, quality, summaries
