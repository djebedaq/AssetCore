from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from .sources import (
    CATALOG_VERSION,
    RESOURCE_ROOT,
    CatalogSourceError,
    dataset_sources,
    load_all_records,
    source_digest,
)

TRANSLATION_VERSION = "CATALOG_EN_BG_V1"
TRANSLATION_ROOT = RESOURCE_ROOT / "catalog" / "enrichment" / "v1"
TRANSLATION_PATH = TRANSLATION_ROOT / "catalog_names_en_bg.json"
ALLOWED_QA_STATUSES = {"VERIFIED", "NEEDS_REVIEW"}


class CatalogTranslationError(RuntimeError):
    pass


def load_translation_payload(path: Path = TRANSLATION_PATH) -> dict[str, Any]:
    if not path.is_file():
        raise CatalogTranslationError("Липсва ресурсът с EN/BG каталожни имена.")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_translation_payload(
    payload: dict[str, Any] | None = None,
    *,
    source_records: list[dict[str, Any]] | None = None,
    verify_source_files: bool = True,
) -> dict[str, Any]:
    payload = payload if payload is not None else load_translation_payload()
    source_records = source_records if source_records is not None else load_all_records()
    errors: list[str] = []
    records = list(payload.get("records") or [])
    source_by_key = {
        str(record.get("source_record_key")): record for record in source_records
    }
    translation_keys = [str(record.get("source_record_key") or "") for record in records]
    duplicate_keys = sorted(
        key for key, count in Counter(translation_keys).items() if key and count > 1
    )
    source_keys = set(source_by_key)
    translation_key_set = {key for key in translation_keys if key}
    orphan_keys = sorted(translation_key_set - source_keys)
    missing_keys = sorted(source_keys - translation_key_set)
    blank_english = sorted(
        str(record.get("source_record_key") or "<missing-key>")
        for record in records
        if not str(record.get("description_en") or "").strip()
    )
    blank_bulgarian = sorted(
        str(record.get("source_record_key") or "<missing-key>")
        for record in records
        if not str(record.get("description_bg") or "").strip()
    )
    invalid_qa = sorted(
        str(record.get("source_record_key") or "<missing-key>")
        for record in records
        if record.get("qa_status") not in ALLOWED_QA_STATUSES
    )
    undocumented_review = sorted(
        str(record.get("source_record_key") or "<missing-key>")
        for record in records
        if record.get("qa_status") == "NEEDS_REVIEW"
        and not str(record.get("qa_note") or "").strip()
    )

    if payload.get("translation_version") != TRANSLATION_VERSION:
        errors.append("invalid translation_version")
    if payload.get("catalog_dataset_version") != CATALOG_VERSION:
        errors.append("translation catalog_dataset_version mismatch")
    if len(records) != len(source_records):
        errors.append(
            f"translation record count {len(records)} != {len(source_records)}"
        )
    if duplicate_keys:
        errors.append(f"duplicate translation identities: {duplicate_keys}")
    if orphan_keys:
        errors.append(f"orphan translations: {orphan_keys}")
    if missing_keys:
        errors.append(f"missing translations: {missing_keys}")
    if blank_english:
        errors.append(f"blank English translations: {blank_english}")
    if blank_bulgarian:
        errors.append(f"blank Bulgarian translations: {blank_bulgarian}")
    if invalid_qa:
        errors.append(f"invalid translation QA status: {invalid_qa}")
    if undocumented_review:
        errors.append(f"undocumented NEEDS_REVIEW translations: {undocumented_review}")

    expected_fingerprints = {
        str(source["source_id"]): str(source["sha256"])
        for source in dataset_sources()
    }
    declared_fingerprints = {
        str(key): str(value)
        for key, value in (
            payload.get("authoritative_source_fingerprints") or {}
        ).items()
    }
    if declared_fingerprints != expected_fingerprints:
        errors.append("authoritative source fingerprint binding mismatch")
    unchanged_source_count = 0
    if verify_source_files:
        for source in dataset_sources():
            source_id = str(source["source_id"])
            try:
                actual_digest = source_digest(source)
            except CatalogSourceError as exc:
                errors.append(str(exc))
                continue
            if actual_digest != expected_fingerprints[source_id]:
                errors.append(f"{source_id}: authoritative source SHA-256 mismatch")
            else:
                unchanged_source_count += 1

    review_records = [
        {
            "source_record_key": str(record["source_record_key"]),
            "description_en": str(record["description_en"]),
            "description_bg": str(record["description_bg"]),
            "qa_note": str(record.get("qa_note") or ""),
        }
        for record in records
        if record.get("qa_status") == "NEEDS_REVIEW"
    ]
    english_coverage = len(records) - len(blank_english)
    bulgarian_coverage = len(records) - len(blank_bulgarian)
    return {
        "translation_version": payload.get("translation_version"),
        "valid": not errors,
        "errors": errors,
        "translation_record_count": len(records),
        "english_translation_coverage": english_coverage,
        "bulgarian_translation_coverage": bulgarian_coverage,
        "orphan_translation_count": len(orphan_keys),
        "missing_translation_count": len(missing_keys),
        "duplicate_translation_key_count": len(duplicate_keys),
        "needs_review_count": len(review_records),
        "needs_review_records": review_records,
        "authoritative_source_fingerprint_count": len(expected_fingerprints),
        "unchanged_authoritative_source_count": unchanged_source_count,
    }


@lru_cache(maxsize=1)
def translation_map() -> dict[str, dict[str, Any]]:
    payload = load_translation_payload()
    report = validate_translation_payload(payload)
    if not report["valid"]:
        raise CatalogTranslationError("; ".join(report["errors"]))
    return {
        str(record["source_record_key"]): record
        for record in payload["records"]
    }


def translation_for(source_record_key: str | None) -> dict[str, Any]:
    translation = translation_map().get(str(source_record_key or ""))
    if translation is None:
        raise CatalogTranslationError(
            f"Липсва EN/BG име за каталожен запис {source_record_key or '—'}."
        )
    return translation


def matching_source_record_keys(query: str) -> set[str]:
    term = query.strip().casefold()
    if not term:
        return set()
    return {
        source_record_key
        for source_record_key, translation in translation_map().items()
        if term in str(translation["description_en"]).casefold()
        or term in str(translation["description_bg"]).casefold()
    }
