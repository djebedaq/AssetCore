"""Build the immutable PARTS_CATALOG_V2 dataset from the controlled PDFs.

This is a maintainer tool, not an application-startup extractor.  It deliberately
reads only the files and page ranges declared below.  Generated JSON is reviewed
and committed; runtime import never uses legacy AssetCore catalog data.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "resources" / "technical_docs" / "PARTS_CATALOG"
OUTPUT_ROOT = ROOT / "resources" / "catalog" / "v2"
DATASET_VERSION = "PARTS_CATALOG_V2"

SOURCES: tuple[dict[str, Any], ...] = (
    {
        "source_id": "falch_500_wheel_jet",
        "family": "FALCH_500",
        "assembly": "WHEEL_JET",
        "records_file": "falch_500/wheel_jet.json",
        "filename": "FALCH_500/WHEEL_JET_PARTLIST.pdf",
        "sha256": "baab518592c770457ba493d056e7e7112ddfa15d45d8db93214fe339ec36af85",
        "page_count": 10,
        "document_reference": "G393-L-00",
        "document_title": "Wheel Jet 15-e 500 bar",
        "source_date": "2024-10-14",
        "diagram_pages": [1, 2, 3],
        "record_pages": [4, 5, 6, 7, 8, 9],
    },
    {
        "source_id": "falch_500_pump",
        "family": "FALCH_500",
        "assembly": "PUMP",
        "records_file": "falch_500/pump.json",
        "filename": "FALCH_500/PUMP_PARTLIST.pdf",
        "sha256": "0f9d3e8d178272b7e65a57a37f495a448fc24c31730ac2c107e5d50f29a317c4",
        "page_count": 4,
        "document_reference": "E0110045-L-00",
        "document_title": "Pump KS 20.1-20-500",
        "source_date": "2025-10-15",
        "diagram_pages": [1],
        "record_pages": [2, 3, 4],
    },
    {
        "source_id": "falch_500_unloader_valve",
        "family": "FALCH_500",
        "assembly": "UNLOADER_VALVE",
        "records_file": "falch_500/unloader_valve.json",
        "filename": "FALCH_500/UNLOADER_VALVE_PARTLIST.pdf",
        "sha256": "5382954ff92c616622b0d4cfdc3a2a12581f442c209c6329d8d2e50cb40fc1d5",
        "page_count": 4,
        "document_reference": "E1110066-L-02",
        "document_title": "Unloader valve RV-HF 30.2-500-E press control",
        "source_date": "2022-05-03",
        "diagram_pages": [1],
        "record_pages": [2, 3, 4],
    },
    {
        "source_id": "falch_500_valve_500bar",
        "family": "FALCH_500",
        "assembly": "VALVE_500BAR",
        "records_file": "falch_500/valve_500bar.json",
        "filename": "FALCH_500/VALVE_500BAR_PARTLIST.pdf",
        "sha256": "ff4a643c60109636e6ebc619551d46ab57b05542fca32a46e3390dec130d14af",
        "page_count": 3,
        "document_reference": "E1190100-L-00",
        "document_title": "Valve 500 bar",
        "source_date": "2023-03-08",
        "diagram_pages": [1],
        "record_pages": [2, 3],
    },
    {
        "source_id": "falch_1000_wheel_jet",
        "family": "FALCH_1000",
        "assembly": "WHEEL_JET",
        "records_file": "falch_1000/wheel_jet.json",
        "filename": "FALCH_1000/WHEEL_JET_PARTLIST.pdf",
        "sha256": "acc612f796ec891cf8aeb0bc86b7150630f7b4874ea370d0c4f5503aff73675d",
        "page_count": 11,
        "document_reference": "G412-L-00",
        "document_title": "Wheel Jet 30-e 1000 bar",
        "source_date": "2024-11-15",
        "diagram_pages": [1, 2, 3],
        "record_pages": [4, 5, 6, 7, 8, 9, 10],
    },
    {
        "source_id": "falch_1000_drive_pump",
        "family": "FALCH_1000",
        "assembly": "DRIVE_PUMP",
        "records_file": "falch_1000/drive_pump.json",
        "filename": "FALCH_1000/PUMP_PARTLIST.pdf",
        "sha256": "81eb5c94e2c2c2a2b8e868acb3721dddfecd642c2744093046fe34fdf9213c82",
        "page_count": 3,
        "document_reference": "E0112004-L-010-0307",
        "document_title": "Drive pump FA 30.1-1000/2000",
        "source_date": "2025-10-15",
        "diagram_pages": [1],
        "record_pages": [2, 3],
    },
    {
        "source_id": "falch_1000_liquid_part",
        "family": "FALCH_1000",
        "assembly": "LIQUID_PART",
        "records_file": "falch_1000/liquid_part.json",
        "filename": "FALCH_1000/LIQUID_PART_PARTLIST.pdf",
        "sha256": "a238920e0392b9c5be56452eef1da9187e530d8dea6925b721784b06418a5278",
        "page_count": 4,
        "document_reference": "E0113679-L-00",
        "document_title": "Liquid part FA 30.1-1000-16 PFS",
        "source_date": "2024-03-08",
        "diagram_pages": [1],
        "record_pages": [2, 3],
    },
    {
        "source_id": "hydwin_fussen_500_scope_instruction",
        "family": "HYDWIN_FUSSEN_500",
        "assembly": "PLUNGER_PUMP",
        "filename": "HYDWIN_FUSEEN_500/READ BEFORE OPEN PDF.txt",
        "sha256": "a3b2978236b8a6c3418fe1738a76edec368ed2c88f6779cb4f57bf4fececdad9",
        "page_count": None,
        "document_reference": None,
        "document_title": "Authoritative plunger-pump scope instruction",
        "source_date": None,
        "allowed_pages": [],
        "allowed_scope": "PLUNGER_PUMP_ONLY",
        "import_status": "SCOPE_CONTROL",
    },
    {
        "source_id": "hydwin_fussen_500_plunger_pump",
        "family": "HYDWIN_FUSSEN_500",
        "assembly": "PLUNGER_PUMP",
        "records_file": "hydwin_fussen_500/plunger_pump.json",
        "filename": "HYDWIN_FUSEEN_500/ONLY_PLUNGER_PUMP.pdf",
        "sha256": "5b5d89b5ebcd71dc8f203d7a6ef419e9f131eaf7f95a1cbe3221992d5c6b7056",
        "page_count": 23,
        "document_reference": None,
        "document_title": "FCE 15/50 High-Pressure Washer User Manual",
        "source_date": None,
        "diagram_pages": [21],
        "record_pages": [22],
        "allowed_pages": [21, 22],
        "allowed_scope": "PLUNGER_PUMP_ONLY",
    },
)

FAMILY_METADATA = {
    "FALCH_500": {
        "brand": "Falch",
        "model": "Wheel Jet 15-e",
        "machine_numbers": ["9", "10", "11", "12", "13", "14", "15", "16"],
    },
    "FALCH_1000": {
        "brand": "Falch",
        "model": "Wheel Jet 30-e",
        "machine_numbers": ["7", "17", "18"],
    },
    "HYDWIN_FUSSEN_500": {
        "brand": "HYDWIN (Fussen)",
        "model": "FCE15/50",
        "machine_numbers": ["20", "21", "22", "23", "24"],
    },
}

# These six labels were checked against rendered source pages.  Coordinates are
# normalized top-left rectangles and remain editable data, never TSX constants.
VERIFIED_HOTSPOTS = {
    "falch_500_valve_500bar": [
        {"page": 1, "position": "3", "x": 0.431, "y": 0.466, "width": 0.035, "height": 0.040},
        {"page": 1, "position": "4", "x": 0.431, "y": 0.501, "width": 0.035, "height": 0.040},
    ],
    "falch_1000_liquid_part": [
        {"page": 1, "position": "6", "x": 0.151, "y": 0.169, "width": 0.034, "height": 0.040},
        {"page": 1, "position": "16", "x": 0.617, "y": 0.446, "width": 0.043, "height": 0.040},
    ],
    "hydwin_fussen_500_plunger_pump": [
        {"page": 21, "position": "34", "x": 0.687, "y": 0.607, "width": 0.043, "height": 0.035},
        {"page": 21, "position": "35", "x": 0.813, "y": 0.661, "width": 0.043, "height": 0.035},
    ],
}

COLUMN_BOUNDS = (
    ("position", 0, 70),
    ("part_number", 70, 130),
    ("replaced_by_part_number", 130, 185),
    ("quantity_raw", 185, 219),
    ("description_de", 219, 374),
    ("description_en", 374, 462),
    ("description_fr", 462, 556),
    ("description_2", 556, 677),
    ("valid_for_raw", 677, 749),
    ("repair_kit_code", 749, 843),
)


def clean(value: str | None) -> str:
    return " ".join((value or "").split())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def group_lines(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    lines: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
        if not lines or abs(lines[-1][0]["top"] - word["top"]) > 0.8:
            lines.append([word])
        else:
            lines[-1].append(word)
    return lines


def parse_falch(source: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    path = SOURCE_ROOT / source["filename"]
    with pdfplumber.open(path) as pdf:
        for page_number in source["record_pages"]:
            words = pdf.pages[page_number - 1].extract_words(
                keep_blank_chars=False, use_text_flow=False
            )
            note_tops = [
                word["top"]
                for word in words
                if 40 <= word["x0"] < 70
                and clean(word["text"]).lower().rstrip(":")
                in {"notiz", "note", "notice"}
                and word["top"] >= 135
            ]
            table_bottom = min(note_tops, default=540.0)
            starts: list[tuple[float, str]] = []
            for line in group_lines(words):
                first = min(line, key=lambda item: item["x0"])
                if (
                    40 <= first["x0"] < 70
                    and re.fullmatch(r"\d+", first["text"])
                    and 135 <= first["top"] < table_bottom
                ):
                    starts.append((first["top"], first["text"]))
            for index, (top, _position) in enumerate(starts, start=1):
                bottom = starts[index][0] if index < len(starts) else table_bottom
                row_words = [
                    word for word in words if top - 0.8 <= word["top"] < bottom - 0.8
                ]
                values = {
                    name: clean(
                        " ".join(
                            word["text"]
                            for word in sorted(
                                row_words, key=lambda item: (item["top"], item["x0"])
                            )
                            if lower <= word["x0"] < upper
                        )
                    )
                    for name, lower, upper in COLUMN_BOUNDS
                }
                quantity = (
                    float(values["quantity_raw"].replace(",", "."))
                    if re.fullmatch(r"\d+(?:[.,]\d+)?", values["quantity_raw"])
                    else None
                )
                records.append(
                    {
                        **values,
                        "source_record_key": (
                            f"{source['source_id']}:p{page_number}:r{index:03d}:"
                            f"{values['position']}:{values['part_number']}"
                        ),
                        "source_row_index": index,
                        "quantity": quantity,
                        "source_page": page_number,
                    }
                )
    return records


def parse_hydwin(source: dict[str, Any]) -> list[dict[str, Any]]:
    path = SOURCE_ROOT / source["filename"]
    with pdfplumber.open(path) as pdf:
        tables = pdf.pages[21].extract_tables(
            {"text_x_tolerance": 1, "text_y_tolerance": 3}
        )
    records: list[dict[str, Any]] = []
    for row_index, row in enumerate(tables[0][1:], start=1):
        for offset in (0, 5):
            position, name, specification, code, quantity_raw = row[offset : offset + 5]
            position_text = clean(position)
            quantity_text = clean(quantity_raw)
            records.append(
                {
                    "position": position_text,
                    "part_number": clean(code),
                    "replaced_by_part_number": "",
                    "quantity_raw": quantity_text,
                    "quantity": (
                        float(quantity_text)
                        if re.fullmatch(r"\d+(?:\.\d+)?", quantity_text)
                        else None
                    ),
                    "description_de": "",
                    "description_en": clean(name),
                    "description_fr": "",
                    "description_2": re.sub(r"Φ\s+", "Φ", clean(specification)),
                    "description_2_raw": clean(specification),
                    "valid_for_raw": "",
                    "repair_kit_code": "",
                    "source_record_key": (
                        "hydwin_fussen_500_plunger_pump:"
                        f"p22:r{int(position_text):03d}"
                    ),
                    "source_row_index": int(position_text),
                    "source_page": 22,
                }
            )
    return sorted(records, key=lambda item: int(item["position"]))


def enrich(source: dict[str, Any], raw_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    family = FAMILY_METADATA[source["family"]]
    position_counts = Counter(record["position"] for record in raw_records)
    result: list[dict[str, Any]] = []
    for raw in raw_records:
        anomalies: list[str] = []
        if not raw["part_number"]:
            anomalies.append("BLANK_PART_NUMBER")
        if raw["quantity"] is None:
            anomalies.append("NON_NUMERIC_QUANTITY")
        if position_counts[raw["position"]] > 1:
            anomalies.append("REPEATED_POSITION_VARIANT")
        result.append(
            {
                **raw,
                "manufacturer": family["brand"],
                "brand": family["brand"],
                "family": source["family"],
                "model": family["model"],
                "assembly": source["assembly"],
                "description": raw["description_en"] or raw["description_de"],
                "original_name": raw["description_de"] or raw["description_en"],
                "technical_specification": raw["description_2"],
                "source_id": source["source_id"],
                "source_document": f"PARTS_CATALOG/{source['filename']}",
                "source_document_sha256": source["sha256"],
                "source_figure": source["document_title"],
                "diagram_page": source["diagram_pages"][0],
                "source_version": DATASET_VERSION,
                "verification_status": "VERIFIED_SOURCE_ROW",
                "is_verified": True,
                "source_anomaly_codes": anomalies,
            }
        )
    return result


def build() -> dict[str, Any]:
    for source in SOURCES:
        path = SOURCE_ROOT / source["filename"]
        if not path.is_file():
            raise RuntimeError(f"Missing controlled source: {source['filename']}")
        if sha256(path) != source["sha256"]:
            raise RuntimeError(f"Controlled-source hash mismatch: {source['filename']}")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_sources: list[dict[str, Any]] = []
    totals = Counter()
    for source in SOURCES:
        manifest_source = {
            **source,
            "allowed_pages": source.get(
                "allowed_pages",
                list(range(1, int(source["page_count"]) + 1))
                if source.get("page_count")
                else [],
            ),
            "import_status": source.get("import_status", "VERIFIED"),
        }
        if "records_file" not in source:
            manifest_sources.append(manifest_source)
            continue
        raw = (
            parse_hydwin(source)
            if source["family"] == "HYDWIN_FUSSEN_500"
            else parse_falch(source)
        )
        records = enrich(source, raw)
        hotspots = [
            {
                **hotspot,
                "hotspot_key": (
                    f"{source['source_id']}:p{hotspot['page']}:"
                    f"{hotspot['position']}:{index:02d}"
                ),
                "source_id": source["source_id"],
                "family": source["family"],
                "assembly": source["assembly"],
                "is_verified": True,
                "provenance": "Визуално проверен етикет върху контролираната PDF схема.",
                "confidence": 1.0,
            }
            for index, hotspot in enumerate(
                VERIFIED_HOTSPOTS.get(source["source_id"], []), start=1
            )
        ]
        output = OUTPUT_ROOT / source["records_file"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "dataset_version": DATASET_VERSION,
                    "source_id": source["source_id"],
                    "family": source["family"],
                    "assembly": source["assembly"],
                    "records": records,
                    "hotspots": hotspots,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        manifest_source["record_count"] = len(records)
        manifest_source["verified_hotspot_count"] = len(hotspots)
        manifest_sources.append(manifest_source)
        totals[source["family"]] += len(records)

    manifest = {
        "dataset_version": DATASET_VERSION,
        "authoritative_scope": "Attached PARTS_CATALOG.zip only",
        "families": FAMILY_METADATA,
        "sources": manifest_sources,
        "record_count": sum(totals.values()),
        "records_by_family": dict(sorted(totals.items())),
        "verified_hotspot_count": sum(
            source.get("verified_hotspot_count", 0) for source in manifest_sources
        ),
    }
    (OUTPUT_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
