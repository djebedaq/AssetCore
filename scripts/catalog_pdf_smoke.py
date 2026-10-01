"""Read-only, DB-free, offline arbitrary-PDF QA, using the production extractor."""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.catalog_admin.ingest.association import relationship  # noqa: E402
from app.catalog_admin.ingest.geometry import match_position  # noqa: E402
from app.catalog_admin.ingest.labels import label_members  # noqa: E402
from app.catalog_admin.ingest.process import configuration, extract  # noqa: E402
from app.catalog_admin.ingest.schema import SCHEMA_VERSION  # noqa: E402
from app.settings import settings  # noqa: E402


def analyze_pdf(path: Path, *, details: bool = False, no_ocr: bool = False) -> dict:
    # Never opens a database or imports app.database. No uploaded/derived files.
    size = path.stat().st_size
    if size > settings.catalog_pdf_max_bytes:
        raise ValueError("CATALOG_PDF_MAX_BYTES")
    with path.open("rb") as source:
        content = source.read(settings.catalog_pdf_max_bytes + 1)
    if len(content) > settings.catalog_pdf_max_bytes:
        raise ValueError("CATALOG_PDF_MAX_BYTES")
    if not content.startswith(b"%PDF-"):
        raise ValueError("catalog_source_invalid_pdf")
    config = configuration(settings)
    if no_ocr:
        config["ocr_enabled"] = False
    validated = extract(content, "validate", 1, config)
    if validated.get("error"):
        raise ValueError(validated["error"])
    count = validated["page_count"]
    roles, methods, warnings, schemas, hotspots = (Counter() for _ in range(5))
    groups, pages = {}, []
    table_count = parts = review_parts = continuations = 0
    previous = None
    group = None
    for number in range(1, count + 1):
        layout = extract(content, "page", number, {**config,
            "previous_heading": previous.get("heading") if previous else None,
            "continuation_tables": previous.get("tables", []) if previous and previous["role"] in {"SPARE_PARTS_LIST", "BOTH"} else []})
        if layout.get("error"):
            warnings[layout["error"]] += 1
            previous, group = None, None
            continue
        relation = relationship(previous, layout)
        continuations += int(relation == "TABLE_CONTINUATION" or any(t.get("continuation_inferred") for t in layout["tables"]))
        if layout.get("heading") and layout["role"] in {"SPARE_PARTS_LIST", "EXPLODED_SCHEME", "BOTH"}:
            group = layout["heading"].casefold()
            groups.setdefault(group, {"name": layout["heading"], "scheme_pages": [], "parts_pages": [], "positions": set(),
                "part_rows": 0, "review_rows": 0, "schemas": Counter(), "sample_rows": []})
        elif not relation:
            group = None
        roles[layout["role"]] += 1
        methods[layout["method"]] += 1
        warnings.update(layout["warnings"])
        table_count += len(layout["tables"])
        schemas.update(table["schema"]["state"] for table in layout["tables"])
        parts += len(layout["rows"])
        review_parts += sum(bool(row["warnings"]) or row["confidence"] < .9 or group is None for row in layout["rows"])
        if group:
            if layout["role"] in {"EXPLODED_SCHEME", "BOTH"}:
                groups[group]["scheme_pages"].append((number, {key: layout[key] for key in
                    ("labels", "method", "ocr_used", "width", "height", "rotation_matrix")}))
            if layout["role"] in {"SPARE_PARTS_LIST", "BOTH"}:
                groups[group]["parts_pages"].append(number)
                groups[group]["positions"].update(row["payload"]["position"] for row in layout["rows"] if row["payload"]["position"])
                groups[group]["part_rows"] += len(layout["rows"])
                groups[group]["review_rows"] += sum(bool(row["warnings"]) or row["confidence"] < .9 for row in layout["rows"])
                groups[group]["schemas"].update(t["schema"]["state"] for t in layout["tables"])
                if len(groups[group]["sample_rows"]) < 5:
                    groups[group]["sample_rows"].extend({"page": number, **row} for row in layout["rows"][:5 - len(groups[group]["sample_rows"])])
        if details:
            pages.append({"page": number, "heading": layout["heading"], "role": layout["role"], "method": layout["method"],
                "association": relation, "heading_evidence": layout.get("heading_evidence", {}),
                "warnings": layout["warnings"], "tables": layout["tables"],
                "sample_rows": layout["rows"][:5], "part_rows": len(layout["rows"]),
                "review_rows": sum(bool(row["warnings"]) or row["confidence"] < .9 for row in layout["rows"]),
                "position_labels": len(layout["labels"]), "role_evidence": layout["role_evidence"]})
        # Keep only previous evidence and schemes, never the full document layout.
        previous = layout
    proposed = []
    for item in groups.values():
        matches = {position: match_position(position, item["scheme_pages"], item["positions"]) for position in sorted(item["positions"])}
        counts = Counter(match["match"] for match in matches.values())
        hotspots.update(counts)
        labels = Counter(label["text"] for _, page in item["scheme_pages"] for label in page["labels"])
        expanded = {member for label in labels for member in label_members(label)
                    if len(label_members(label)) == 1 or set(label_members(label)) <= item["positions"]}
        proposed.append({"name": item["name"], "scheme_pages": [number for number, _ in item["scheme_pages"]],
            "parts_pages": item["parts_pages"], "positions": len(item["positions"]), "part_rows": item["part_rows"],
            "review_rows": item["review_rows"], "schemas": dict(item["schemas"]), "hotspots": dict(counts),
            **({"sample_rows": item["sample_rows"], "vocabulary": {"bom": sorted(item["positions"]),
                "diagram": sorted(expanded), "intersection": sorted(item["positions"] & expanded),
                "bom_only": sorted(item["positions"] - expanded), "diagram_only": sorted(expanded - item["positions"]),
                "repeated": {label: count for label, count in labels.items() if count > 1},
                "combined": {label: label_members(label) for label in labels if len(label_members(label)) > 1}},
                "exact_samples": [{"position": position, **match["locations"][0]} for position, match in matches.items()
                    if match["match"] == "EXACT"][:10],
                "unresolved": {position: match["match"] for position, match in matches.items() if match["match"] != "EXACT"}}
                if details else {})})
    return {"filename": path.name, "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content),
        "page_count": count, "schema_version": SCHEMA_VERSION, "native_pages": methods["NATIVE"], "ocr_pages": methods["OCR"],
        "proposed_groups": proposed, "roles": {role: roles[role] for role in ["EXPLODED_SCHEME", "SPARE_PARTS_LIST", "BOTH", "AMBIGUOUS", "OTHER"]},
        "detected_tables": table_count, "resolved_bom_schemas": schemas["RESOLVED"], "ambiguous_bom_schemas": schemas["NEEDS_REVIEW"],
        "continuation_pages": continuations,
        "extracted_parts": parts, "parts_needing_review": review_parts,
        "hotspots": {match: hotspots[match] for match in ["EXACT", "MULTIPLE_CANDIDATES", "NOT_FOUND", "LOW_CONFIDENCE"]},
        "warnings": dict(warnings), **({"pages": pages} if details else {})}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--details", action="store_true", help="Include per-page table schema evidence and sample rows")
    parser.add_argument("--no-ocr", action="store_true", help="Disable optional local OCR")
    args = parser.parse_args()
    try:
        report = analyze_pdf(args.pdf, details=args.details, no_ocr=args.no_ocr)
    except Exception as exc:
        # Do not expose native diagnostics, absolute paths, or environment values.
        code = str(exc) if isinstance(exc, ValueError) and str(exc).replace("_", "").isalnum() else "catalog_pdf_qa_failed"
        print(json.dumps({"error": code}))
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
