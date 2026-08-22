from __future__ import annotations

import argparse
import json

from app.catalog.sources import CATALOG_VERSION, dataset_sources, load_all_records
from app.catalog.translations import (
    TRANSLATION_PATH,
    TRANSLATION_ROOT,
    TRANSLATION_VERSION,
)

TERMINOLOGY_PATH = TRANSLATION_ROOT / "terminology_en_bg.json"


def _normalized(value: object) -> str:
    return str(value or "").strip().casefold()


def build_payload() -> dict:
    terminology_payload = json.loads(TERMINOLOGY_PATH.read_text(encoding="utf-8"))
    if terminology_payload.get("translation_version") != TRANSLATION_VERSION:
        raise ValueError("Terminology translation_version mismatch.")
    terminology: dict[str, dict] = {}
    for item in terminology_payload.get("terms") or []:
        source_term = _normalized(item.get("source_term"))
        if not source_term:
            raise ValueError("Blank source term in terminology resource.")
        if source_term in terminology:
            raise ValueError(f"Duplicate terminology source term: {source_term}")
        if not str(item.get("description_en") or "").strip():
            raise ValueError(f"Blank English name for terminology term: {source_term}")
        if not str(item.get("description_bg") or "").strip():
            raise ValueError(f"Blank Bulgarian name for terminology term: {source_term}")
        terminology[source_term] = item

    records = []
    used_terms: set[str] = set()
    for source_record in load_all_records():
        source_term = _normalized(
            source_record.get("description_en") or source_record.get("description")
        )
        item = terminology.get(source_term)
        if item is None:
            raise ValueError(
                f"Missing curated terminology for {source_record['source_record_key']}: "
                f"{source_term!r}"
            )
        used_terms.add(source_term)
        record = {
            "source_record_key": source_record["source_record_key"],
            "description_en": str(item["description_en"]).strip(),
            "description_bg": str(item["description_bg"]).strip(),
            "qa_status": item.get("qa_status", "VERIFIED"),
        }
        if item.get("qa_note"):
            record["qa_note"] = str(item["qa_note"]).strip()
        records.append(record)

    unused_terms = sorted(set(terminology) - used_terms)
    if unused_terms:
        raise ValueError(f"Orphan terminology terms: {unused_terms}")
    return {
        "translation_version": TRANSLATION_VERSION,
        "catalog_dataset_version": CATALOG_VERSION,
        "identity_field": "source_record_key",
        "authoritative_source_fingerprints": {
            source["source_id"]: source["sha256"] for source in dataset_sources()
        },
        "records": sorted(records, key=lambda item: item["source_record_key"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(build_payload(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not TRANSLATION_PATH.is_file():
            raise SystemExit("Generated catalog translation resource is missing.")
        if TRANSLATION_PATH.read_text(encoding="utf-8") != expected:
            raise SystemExit("Generated catalog translation resource is out of date.")
        return 0
    TRANSLATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRANSLATION_PATH.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
