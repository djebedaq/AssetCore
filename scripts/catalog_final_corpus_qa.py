"""03D real library corpus: extraction and independent comparison are separate modes.

Extract output contains OEM rows: keep it private/ignored. Compare emits aggregate
counts only. The fixture selection contains physical pages, never expected values.
Existing verified source controls are loaded only by the compare command.
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace

from catalog_adaptive_pdf_qa import extract_report

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ("falch_1000/drive_pump", "FALCH_1000/PUMP_PARTLIST.pdf", "2,3"),
    ("falch_1000/liquid_part", "FALCH_1000/LIQUID_PART_PARTLIST.pdf", "2,3"),
    ("falch_1000/wheel_jet", "FALCH_1000/WHEEL_JET_PARTLIST.pdf", "4,5,6,7,8,9"),
    ("falch_500/pump", "FALCH_500/PUMP_PARTLIST.pdf", "2,3,4"),
    ("falch_500/unloader_valve", "FALCH_500/UNLOADER_VALVE_PARTLIST.pdf", "2,3,4"),
    ("falch_500/valve_500bar", "FALCH_500/VALVE_500BAR_PARTLIST.pdf", "2,3"),
    ("falch_500/wheel_jet", "FALCH_500/WHEEL_JET_PARTLIST.pdf", "4,5,6,7,8"),
    ("hydwin_fussen_500/plunger_pump", "HYDWIN_FUSEEN_500/ONLY_PLUNGER_PUMP.pdf", "22"),
]


def extract():
    reports = []
    for key, document, pages in CASES:
        report = extract_report(SimpleNamespace(pdf=ROOT / "backend/resources/technical_docs/PARTS_CATALOG" / document,
            pages=pages, runs=1))
        reports.append({"case": key, "report": report})
    return reports


def quantity(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def compare(reports):
    cases = []
    for item in reports:
        key, report = item["case"], item["report"]
        # No expected data was read until all extraction reports were saved.
        control = ROOT / "backend/resources/catalog/v2" / (key + ".json")
        expected = json.loads(control.read_text(encoding="utf-8"))["records"]
        assert all(row["source_document_sha256"] == report["source_sha256"] for row in expected)
        pages = []
        for page in report["runs"][0]["pages"]:
            wanted = [row for row in expected if row["source_page"] == page["physical_page"]]
            actual = [row["payload"] for row in page["result"].get("rows", [])]
            # Preserve duplicate source occurrences; consume each match once.
            matched = Counter()
            for row, value in zip(wanted, actual, strict=False):
                matched["position"] += value.get("position") == row["position"]
                matched["part_number"] += value.get("part_number") == row["part_number"]
                matched["quantity_raw"] += value.get("quantity_raw") == row["quantity_raw"]
                parsed = quantity(value.get("quantity"))
                matched["numeric_quantity"] += parsed is not None and parsed == quantity(row["quantity"])
                matched["original_description"] += bool(value.get("description")) and value.get("description") in {
                    row.get("description_de"), row.get("description_en"), row.get("description_fr"), row.get("original_name")}
            unused = list(actual)
            for row in wanted:
                index = next((i for i, value in enumerate(unused) if value.get("position") == row["position"]
                    and value.get("part_number") == row["part_number"]), None)
                if index is None:
                    continue
                unused.pop(index)
            provenance = all(row.get("provenance", {}).get("sha256") == report["source_sha256"]
                and row["provenance"].get("physical_page") == page["physical_page"] for row in page["result"].get("rows", []))
            pages.append({"physical_page": page["physical_page"], "expected_rows": len(wanted),
                "extracted_candidates": len(actual), "exact_fields": {field: matched[field] for field in
                    ("position", "part_number", "quantity_raw", "numeric_quantity", "original_description")},
                "unmatched_candidates": len(unused), "provenance": provenance,
                "quality": page["result"].get("quality"), "error": page["result"].get("error"),
                "resources": page["resources"], "review_state": "NOT_REVIEWED"})
        cases.append({"case": key, "source_sha256": report["source_sha256"],
            "control_sha256": hashlib.sha256(control.read_bytes()).hexdigest(), "pages": pages})
    return {"scope": "REAL_EXISTING_VERIFIED_LIBRARY_POST_EXTRACTION_COMPARISON", "cases": cases,
        "universal_manufacturer_accuracy_claim": False, "hammelmann": "NOT_AVAILABLE"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("extract", "compare"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "compare" and not args.report:
        parser.error("compare requires the saved extraction --report")
    result = extract() if args.mode == "extract" else compare(json.loads(args.report.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"mode": args.mode, "cases": len(result if isinstance(result, list) else result["cases"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
