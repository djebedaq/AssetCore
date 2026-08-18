from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..application_errors import ApplicationError
from ..models import CatalogDiagram, Machine, PartCatalog, RepairKit
from . import repository
from .sources import (
    CATALOG_VERSION,
    CatalogSourceError,
    dataset_sources,
    ensure_source_integrity,
    load_manifest,
    source_by_id,
)

UNSUPPORTED_MESSAGE = "Няма потвърдена каталожна документация за този модел."


def _source_error(exc: CatalogSourceError, *, source_id: str | None = None) -> ApplicationError:
    return ApplicationError(
        status_code=503,
        code="catalog_source_integrity_failed",
        message=(
            "Каталогът е временно недостъпен, защото оригиналният източник "
            "не премина проверката за цялост."
        ),
        data={"source_id": source_id} if source_id else {},
        operation="catalog_read",
        stage="source_integrity",
    )


def ensure_integrity(source_id: str) -> dict[str, Any]:
    try:
        return ensure_source_integrity(source_id)
    except CatalogSourceError as exc:
        raise _source_error(exc, source_id=source_id) from exc


def machine_family(machine: Machine) -> str | None:
    for family, metadata in load_manifest()["families"].items():
        if (
            machine.brand == metadata["brand"]
            and machine.model == metadata["model"]
            and str(machine.inventory_number) in {str(value) for value in metadata["machine_numbers"]}
        ):
            return family
    return None


def require_machine(db: Session, machine_id: int) -> Machine:
    machine = db.get(Machine, machine_id)
    if machine is None:
        raise ApplicationError(
            status_code=404,
            code="catalog_machine_not_found",
            message="Машината не е намерена.",
            operation="catalog_read",
            stage="machine_lookup",
        )
    return machine


def serialize_part(part: PartCatalog) -> dict[str, Any]:
    return {
        "id": part.id,
        "source_record_key": part.source_record_key,
        "source_id": part.source_id,
        "source_row_index": part.source_row_index,
        "family": part.family,
        "brand": part.brand,
        "model": part.model,
        "assembly": part.assembly,
        "position": part.position,
        "part_number": part.part_number,
        "order_part_number": part.replaced_by_part_number or part.part_number,
        "replaced_by_part_number": part.replaced_by_part_number,
        "description": part.description,
        "original_name": part.original_name,
        "description_2": part.description_2,
        "quantity": part.quantity,
        "quantity_raw": part.quantity_raw or "",
        "valid_for_raw": part.valid_for_raw,
        "repair_kit_code": part.repair_kit_code,
        "source_document": part.source_document,
        "source_page": part.source_page,
        "source_figure": part.source_figure,
        "source_version": part.source_version,
        "source_document_sha256": part.source_document_sha256,
        "verification_status": part.verification_status,
        "source_anomaly_codes": part.source_anomaly_codes or [],
        "is_verified": part.is_verified,
    }


def serialize_diagram(diagram: CatalogDiagram) -> dict[str, Any]:
    return {
        "id": diagram.id,
        "source_id": diagram.source_id,
        "page_number": diagram.page_number,
        "title": diagram.title,
        "source_pdf_sha256": diagram.source_pdf_sha256,
        "render_version": diagram.render_version,
        "technical_document_id": diagram.technical_document_id,
        "preview_endpoint": (
            f"/technical-library/{diagram.technical_document_id}/pages/"
            f"{diagram.page_number}/preview?scale=2"
        ),
        "download_endpoint": f"/technical-library/{diagram.technical_document_id}/download",
    }


def machine_catalog(db: Session, machine_id: int) -> dict[str, Any]:
    machine = require_machine(db, machine_id)
    family = machine_family(machine)
    base = {
        "dataset_version": CATALOG_VERSION,
        "machine_id": machine.id,
        "machine_number": str(machine.inventory_number),
        "brand": machine.brand,
        "model": machine.model,
    }
    if family is None:
        return {
            **base,
            "supported": False,
            "message": UNSUPPORTED_MESSAGE,
            "family": None,
            "assemblies": [],
        }
    assemblies = []
    for source in dataset_sources():
        if source.get("family") != family or not source.get("records_file"):
            continue
        ensure_integrity(source["source_id"])
        diagrams = repository.diagrams_for_source(db, source["source_id"])
        assemblies.append(
            {
                "source_id": source["source_id"],
                "family": family,
                "assembly": source["assembly"],
                "title": source["document_title"],
                "document_reference": source.get("document_reference"),
                "part_count": int(source["record_count"]),
                "diagram_count": len(diagrams),
                "verified_hotspot_count": repository.verified_hotspot_count(
                    db, source["source_id"]
                ),
                "diagrams": [serialize_diagram(diagram) for diagram in diagrams],
            }
        )
    return {
        **base,
        "supported": True,
        "message": "Каталогът е проверен спрямо оригиналните source файлове.",
        "family": family,
        "assemblies": assemblies,
    }


def require_compatible_source(
    db: Session, *, machine_id: int, source_id: str
) -> tuple[Machine, dict[str, Any]]:
    machine = require_machine(db, machine_id)
    family = machine_family(machine)
    try:
        source = source_by_id(source_id)
    except CatalogSourceError as exc:
        raise ApplicationError(
            status_code=404,
            code="catalog_source_not_found",
            message="Каталожният възел не е намерен.",
            operation="catalog_read",
            stage="source_lookup",
        ) from exc
    if not source.get("records_file"):
        raise ApplicationError(
            status_code=404,
            code="catalog_assembly_not_found",
            message="Каталожният възел не е намерен.",
            operation="catalog_read",
            stage="assembly_lookup",
        )
    if family is None or source["family"] != family:
        raise ApplicationError(
            status_code=409,
            code="catalog_family_mismatch",
            message="Избраният каталожен възел не е потвърден за тази машина.",
            data={"machine_number": str(machine.inventory_number), "source_id": source_id},
            operation="catalog_read",
            stage="compatibility",
        )
    ensure_integrity(source_id)
    return machine, source


def assembly_details(db: Session, *, machine_id: int, source_id: str) -> dict[str, Any]:
    machine, source = require_compatible_source(
        db, machine_id=machine_id, source_id=source_id
    )
    return {
        "dataset_version": CATALOG_VERSION,
        "machine_id": machine.id,
        "machine_number": str(machine.inventory_number),
        "family": source["family"],
        "source_id": source_id,
        "assembly": source["assembly"],
        "title": source["document_title"],
        "diagrams": [
            serialize_diagram(diagram)
            for diagram in repository.diagrams_for_source(db, source_id)
        ],
        "parts": [
            serialize_part(part) for part in repository.parts_for_source(db, source_id)
        ],
    }


def search(
    db: Session,
    *,
    machine_id: int,
    query: str,
    source_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    machine = require_machine(db, machine_id)
    family = machine_family(machine)
    if family is None:
        return []
    if source_id:
        require_compatible_source(db, machine_id=machine_id, source_id=source_id)
    else:
        for source in dataset_sources():
            if source.get("family") == family and source.get("records_file"):
                ensure_integrity(source["source_id"])
    return [
        serialize_part(part)
        for part in repository.search_parts(
            db, query=query, family=family, source_id=source_id, limit=limit
        )
    ]


def diagram_hotspots(
    db: Session, *, diagram_id: int, machine_id: int, verified_only: bool
) -> list[dict[str, Any]]:
    diagram = db.get(CatalogDiagram, diagram_id)
    if diagram is None:
        raise ApplicationError(
            status_code=404,
            code="catalog_diagram_not_found",
            message="Схемата не е намерена.",
            operation="catalog_read",
            stage="diagram_lookup",
        )
    require_compatible_source(db, machine_id=machine_id, source_id=diagram.source_id)
    variants = repository.parts_for_source(db, diagram.source_id)
    by_position: dict[str, list[PartCatalog]] = {}
    for part in variants:
        by_position.setdefault(str(part.position), []).append(part)
    return [
        {
            "id": hotspot.id,
            "hotspot_key": hotspot.hotspot_key,
            "diagram_id": hotspot.diagram_id,
            "page_number": diagram.page_number,
            "position": hotspot.position,
            "x": hotspot.x,
            "y": hotspot.y,
            "width": hotspot.width,
            "height": hotspot.height,
            "is_verified": hotspot.is_verified,
            "provenance": hotspot.provenance,
            "confidence": hotspot.confidence,
            "variants": [
                serialize_part(part) for part in by_position.get(hotspot.position, [])
            ],
        }
        for hotspot in repository.hotspots_for_diagram(
            db, diagram_id, verified_only=verified_only
        )
    ]


def serialize_kit(kit: RepairKit) -> dict[str, Any]:
    return {
        "id": kit.id,
        "code": kit.code,
        "name": kit.name,
        "family": kit.family,
        "source_id": kit.source_id,
        "brand": kit.brand,
        "model": kit.model,
        "assembly": kit.assembly,
        "source_document": kit.source_document,
        "source_page": kit.source_page,
        "source_document_sha256": kit.source_document_sha256,
        "source_version": kit.source_version,
        "is_approved": kit.is_approved,
        "is_active": kit.is_active,
        "components": [
            {
                "id": component.id,
                "part_id": component.part_id,
                "source_record_key": component.source_record_key,
                "position": component.part.position,
                "part_number": component.part.part_number,
                "description": component.part.description,
                "quantity": component.quantity,
                "quantity_raw": component.quantity_raw or "",
                "source_document": component.source_document,
                "source_page": component.source_page,
            }
            for component in sorted(
                kit.components,
                key=lambda item: (
                    item.part.source_page or 0,
                    item.part.source_row_index or 0,
                    item.id,
                ),
            )
        ],
    }


def kits(
    db: Session, *, machine_id: int, source_id: str | None = None
) -> list[dict[str, Any]]:
    machine = require_machine(db, machine_id)
    family = machine_family(machine)
    if family is None:
        return []
    if source_id:
        require_compatible_source(db, machine_id=machine_id, source_id=source_id)
    return [
        serialize_kit(kit)
        for kit in repository.repair_kits(db, family=family, source_id=source_id)
    ]


def kit_details(db: Session, *, machine_id: int, kit_id: int) -> dict[str, Any]:
    available = kits(db, machine_id=machine_id)
    kit = next((item for item in available if item["id"] == kit_id), None)
    if kit is None:
        raise ApplicationError(
            status_code=404,
            code="catalog_repair_kit_not_found",
            message="Ремонтният комплект не е намерен за избраната машина.",
            operation="catalog_read",
            stage="repair_kit_lookup",
        )
    return kit
