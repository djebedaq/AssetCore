from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from pypdf import PdfReader

from .sources import (
    CATALOG_VERSION,
    CatalogSourceError,
    dataset_sources,
    load_manifest,
    load_source_dataset,
    source_digest,
    source_path,
)

HYDWIN_ANCHORS = {
    "13": ("Plunger rod", "FS C16/50 22*145.5", "7.906-002.1", 3.0),
    "15": ("Ceramic tube", "Φ15*Φ8*46 C1650", "7.906-003.4", 3.0),
    "34": ("Main water seal", "15*24*9.3", "7.906-007.11", 3.0),
    "35": ("Pump head", "166*89*86", "7.906-031", 1.0),
}

FALCH_ANCHORS = {
    ("falch_500_valve_500bar", "3"): ("E1230058", "valve seat", "E1800023", 1.0),
    ("falch_500_valve_500bar", "4"): ("E1230059", "holder", "E1800023", 1.0),
    ("falch_1000_liquid_part", "6"): ("X4720000", "safety ring", "E1800040", 3.0),
    ("falch_1000_liquid_part", "16"): ("E1230967", "valve guide", "E0113687", 3.0),
}


def validate_catalog_v2() -> dict[str, Any]:
    manifest = load_manifest()
    errors: list[str] = []
    warnings: list[str] = []
    records: list[dict[str, Any]] = []
    hotspots: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}

    if manifest.get("dataset_version") != CATALOG_VERSION:
        errors.append("manifest: invalid dataset_version")

    for source in dataset_sources():
        try:
            actual_hash = source_digest(source)
        except CatalogSourceError as exc:
            errors.append(str(exc))
            continue
        if actual_hash != source.get("sha256"):
            errors.append(f"{source['source_id']}: SHA-256 mismatch")
        page_count = source.get("page_count")
        if page_count is not None:
            actual_pages = len(PdfReader(str(source_path(source))).pages)
            if actual_pages != page_count:
                errors.append(
                    f"{source['source_id']}: page count {actual_pages} != {page_count}"
                )
        payload = load_source_dataset(source)
        source_records = list(payload.get("records") or [])
        source_hotspots = list(payload.get("hotspots") or [])
        if len(source_records) != int(source.get("record_count") or 0):
            errors.append(f"{source['source_id']}: record count mismatch")
        source_counts[source["source_id"]] = len(source_records)
        allowed_record_pages = set(source.get("record_pages") or [])
        for row in source_records:
            if row.get("source_id") != source.get("source_id"):
                errors.append(f"{source['source_id']}: record source_id mismatch")
            if row.get("family") != source.get("family"):
                errors.append(f"{source['source_id']}: record family mismatch")
            if row.get("assembly") != source.get("assembly"):
                errors.append(f"{source['source_id']}: record assembly mismatch")
            if row.get("source_document_sha256") != source.get("sha256"):
                errors.append(f"{source['source_id']}: record source hash mismatch")
            if row.get("source_page") not in allowed_record_pages:
                errors.append(
                    f"{row.get('source_record_key')}: source page outside record scope"
                )
            if not row.get("source_record_key") or not row.get("position"):
                errors.append(f"{source['source_id']}: missing source identity")
            if row.get("part_number") == "" and "BLANK_PART_NUMBER" not in (
                row.get("source_anomaly_codes") or []
            ):
                errors.append(f"{row.get('source_record_key')}: undocumented blank code")
        positions = {str(row.get("position")) for row in source_records}
        for hotspot in source_hotspots:
            if hotspot.get("position") not in positions:
                errors.append(f"{hotspot.get('hotspot_key')}: orphan hotspot")
            if hotspot.get("page") not in set(source.get("diagram_pages") or []):
                errors.append(f"{hotspot.get('hotspot_key')}: invalid diagram page")
            for coordinate in ("x", "y", "width", "height"):
                value = hotspot.get(coordinate)
                if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                    errors.append(f"{hotspot.get('hotspot_key')}: invalid {coordinate}")
            if hotspot.get("is_verified") and not hotspot.get("provenance"):
                errors.append(f"{hotspot.get('hotspot_key')}: verified without provenance")
        records.extend(source_records)
        hotspots.extend(source_hotspots)

    keys = [row.get("source_record_key") for row in records]
    duplicate_keys = sorted(key for key, count in Counter(keys).items() if count > 1)
    if duplicate_keys:
        errors.append(f"duplicate source_record_key: {duplicate_keys}")

    hydwin = [row for row in records if row.get("family") == "HYDWIN_FUSSEN_500"]
    if len(hydwin) != 58:
        errors.append(f"HYDWIN: expected 58 BOM rows, found {len(hydwin)}")
    if {row.get("source_page") for row in hydwin} - {22}:
        errors.append("HYDWIN: catalog rows outside PDF page 22")
    hydwin_by_position = {row["position"]: row for row in hydwin}
    for position, expected in HYDWIN_ANCHORS.items():
        row = hydwin_by_position.get(position)
        actual = (
            row.get("description_en") if row else None,
            row.get("description_2") if row else None,
            row.get("part_number") if row else None,
            row.get("quantity") if row else None,
        )
        if actual != expected:
            errors.append(f"HYDWIN anchor {position}: {actual!r} != {expected!r}")

    by_source_position: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_source_position[(row["source_id"], row["position"])].append(row)
    for key, expected in FALCH_ANCHORS.items():
        matching = [
            row
            for row in by_source_position.get(key, [])
            if (
                row.get("part_number"),
                row.get("description_en"),
                row.get("repair_kit_code"),
                row.get("quantity"),
            )
            == expected
        ]
        if len(matching) != 1:
            errors.append(f"Falch anchor {key}: expected exactly one matching row")

    allowed_families = {"FALCH_500", "FALCH_1000", "HYDWIN_FUSSEN_500"}
    found_families = {row.get("family") for row in records}
    if found_families != allowed_families:
        errors.append(f"unexpected family set: {sorted(found_families)}")
    if any(row.get("brand") == "CombiJet" for row in records):
        errors.append("CombiJet must not receive catalog rows without a source")

    kit_rows = [row for row in records if row.get("repair_kit_code")]
    kit_codes = sorted({row["repair_kit_code"] for row in kit_rows})
    for row in kit_rows:
        if not row.get("source_record_key"):
            errors.append("orphan repair-kit membership")

    non_numeric = [row for row in records if row.get("quantity") is None]
    if len(non_numeric) != 1 or non_numeric[0].get("quantity_raw") != "1 each":
        errors.append("unexpected non-numeric quantity set")
    blank_codes = [row for row in records if not row.get("part_number")]
    if len(blank_codes) != 3:
        errors.append(f"expected 3 source blank part codes, found {len(blank_codes)}")

    return {
        "dataset_version": CATALOG_VERSION,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "source_count": len(dataset_sources()),
        "record_count": len(records),
        "records_by_family": dict(
            sorted(Counter(row["family"] for row in records).items())
        ),
        "records_by_source": dict(sorted(source_counts.items())),
        "repair_kit_count": len(kit_codes),
        "repair_kit_component_count": len(kit_rows),
        "verified_hotspot_count": sum(bool(row.get("is_verified")) for row in hotspots),
        "hotspot_count": len(hotspots),
        "blank_part_number_count": len(blank_codes),
        "non_numeric_quantity_count": len(non_numeric),
        "replaced_by_count": sum(bool(row.get("replaced_by_part_number")) for row in records),
    }
