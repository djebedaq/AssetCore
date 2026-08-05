from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PartCatalog, TechnicalDocument, User, utcnow

CATALOG_PATH = Path(__file__).resolve().parents[1] / "resources" / "catalog" / "verified_parts_v1.json"
TECHNICAL_DOCS_ROOT = Path(__file__).resolve().parents[1] / "resources" / "technical_docs"


class CatalogImportError(RuntimeError):
    pass


def load_verified_catalog() -> dict[str, Any]:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    validation = payload.get("validation") or {}
    if validation.get("errors"):
        raise CatalogImportError("Каталогът съдържа грешки от предварителната валидация.")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise CatalogImportError("Провереният каталог не съдържа записи.")
    return payload


def _validate_source(record: dict[str, Any]) -> None:
    relative = record.get("source_document")
    expected_hash = record.get("source_document_sha256")
    if not relative or not expected_hash:
        raise CatalogImportError("Каталожен запис няма източник или SHA-256.")
    source = TECHNICAL_DOCS_ROOT / relative
    if not source.is_file():
        raise CatalogImportError(f"Липсва каталожен източник: {relative}")
    actual_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise CatalogImportError(f"Променен каталожен източник без повторна верификация: {relative}")


def import_verified_catalog(db: Session, verifier: User) -> dict[str, Any]:
    payload = load_verified_catalog()
    created = 0
    updated = 0
    by_brand: dict[str, int] = {}

    for data in payload["records"]:
        _validate_source(data)
        key = (
            data["brand"], data.get("model"), data.get("assembly"),
            str(data.get("position") or ""), data["part_number"],
        )
        item = db.scalar(
            select(PartCatalog).where(
                PartCatalog.brand == key[0],
                PartCatalog.model == key[1],
                PartCatalog.assembly == key[2],
                PartCatalog.position == key[3],
                PartCatalog.part_number == key[4],
            )
        )
        if item is None:
            item = PartCatalog(
                brand=key[0], model=key[1], assembly=key[2],
                position=key[3], part_number=key[4],
                description=data["description"],
            )
            db.add(item)
            created += 1
        else:
            updated += 1

        for field in (
            "manufacturer", "category", "name_bg", "name_en", "name_ru",
            "original_name", "description", "quantity", "unit",
            "technical_specification", "compatible_models",
            "compatible_machine_numbers", "technical_notes", "supplier",
            "supplier_code", "estimated_price", "currency", "lead_time_days",
            "revision", "alternative_part_number", "alternative_part_numbers",
            "replacement_part_ids", "replaced_by_part_number", "source_document",
            "source_page", "source_figure", "diagram_page", "source_version",
            "source_document_sha256", "source_excerpt", "provenance_confidence",
            "verification_status",
        ):
            setattr(item, field, data.get(field))
        item.is_active = True
        item.is_verified = True
        item.verified_by_id = verifier.id
        item.verified_at = item.verified_at or utcnow()
        by_brand[item.brand] = by_brand.get(item.brand, 0) + 1

    # Update technical-library metadata from the same immutable manifest.
    sources = payload.get("sources") or {}
    for relative, metadata in sources.items():
        document = db.scalar(select(TechnicalDocument).where(TechnicalDocument.file_path == relative))
        if document is None:
            continue
        document.sha256 = metadata.get("sha256") or document.sha256
        document.page_count = metadata.get("pages") or document.page_count
        if metadata.get("status") == "VALIDATED_NOT_IMPORTED":
            document.notes = metadata.get("reason")

    db.flush()
    return {
        "catalog_version": payload.get("catalog_version"),
        "created": created,
        "updated": updated,
        "total": len(payload["records"]),
        "by_brand": dict(sorted(by_brand.items())),
    }
