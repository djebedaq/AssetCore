from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..application_errors import ApplicationError
from ..assets.capabilities import supports as asset_supports
from ..models import (
    CatalogDefinition,
    CatalogDiagram,
    CatalogRevisionArtifact,
    CatalogRevisionAssembly,
    CatalogVisualSource,
    Machine,
    PartCatalog,
    RepairKit,
    TechnicalDocument,
)
from . import repository
from .runtime_context import published_binding
from .sources import (
    CATALOG_ROOT,
    CATALOG_VERSION,
    CatalogSourceError,
    dataset_sources,
    ensure_source_integrity,
    load_manifest,
    source_by_id,
)
from .translations import (
    TRANSLATION_VERSION,
    CatalogTranslationError,
    matching_source_record_keys,
    translation_for,
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


def _translation_error(exc: CatalogTranslationError) -> ApplicationError:
    return ApplicationError(
        status_code=503,
        code="catalog_translation_integrity_failed",
        message=(
            "Каталогът е временно недостъпен, защото EN/BG имената "
            "не преминаха проверката за цялост."
        ),
        operation="catalog_read",
        stage="translation_integrity",
    )


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
    if part.builder_revision_id is not None:
        translation = {"description_en": part.name_en or part.description,
                       "description_bg": part.name_bg or part.description,
                       "qa_status": "BUILDER_SOURCE"}
        translation_version = "BUILDER"
    else:
        try:
            translation = translation_for(part.source_record_key)
        except CatalogTranslationError as exc:
            raise _translation_error(exc) from exc
        translation_version = TRANSLATION_VERSION
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
        "source_description": part.original_name or part.description,
        "description_en": translation["description_en"],
        "description_bg": translation["description_bg"],
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
        "translation_version": translation_version,
        "translation_qa_status": translation["qa_status"],
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


def _builder_integrity(db: Session, revision_id: int) -> None:
    sources = db.scalars(select(CatalogVisualSource).where(
        CatalogVisualSource.builder_revision_id == revision_id)).all()
    for source in sources:
        document = db.get(TechnicalDocument, source.technical_document_id)
        artifact = db.get(CatalogRevisionArtifact, document.builder_artifact_id) if document and document.builder_artifact_id else None
        diagram = db.scalar(select(CatalogDiagram).where(
            CatalogDiagram.builder_visual_page_id == source.builder_visual_page_id)) if source.role == "EXPLODED_SCHEME" else None
        if (document is None or document.builder_artifact_id is None
                or artifact is None or artifact.sha256 != source.source_sha256
                or hashlib.sha256(artifact.content).hexdigest() != artifact.sha256
                or artifact.content != document.uploaded_content
                or document.uploaded_content is None
                or hashlib.sha256(document.uploaded_content).hexdigest() != source.source_sha256
                or document.sha256 != source.source_sha256
                or not 1 <= source.page_number <= artifact.page_count
                or source.builder_revision_id != revision_id
                or source.role == "EXPLODED_SCHEME" and
                (diagram is None or diagram.source_pdf_sha256 != source.source_sha256 or
                 diagram.technical_document_id != document.id)
                or source.catalog_revision != f"CATALOG_BUILDER_R{revision_id}"):
            raise ApplicationError(status_code=503, code="catalog_publication_integrity_failed",
                                   message="Публикуваният каталог не премина проверката за цялост.",
                                   operation="catalog_read", stage="source_integrity")


def _builder_assembly(db: Session, revision_id: int, source_id: str) -> CatalogRevisionAssembly | None:
    for assembly in db.scalars(select(CatalogRevisionAssembly).where(
            CatalogRevisionAssembly.revision_id == revision_id)):
        if source_id == f"CBR{revision_id}A{assembly.id}":
            return assembly
    return None


def machine_catalog(db: Session, machine_id: int) -> dict[str, Any]:
    machine = require_machine(db, machine_id)
    binding = published_binding(db, machine)
    family = machine_family(machine)
    base = {
        "dataset_version": CATALOG_VERSION,
        "machine_id": machine.id,
        "machine_number": str(machine.inventory_number),
        "brand": machine.brand,
        "model": machine.model,
    }
    if binding is not None and asset_supports(machine, "HAS_PARTS_CATALOG"):
        _builder_integrity(db, binding.revision_id)
        catalog_code = db.get(CatalogDefinition, binding.catalog_id).code
        assemblies = []
        for assembly in db.scalars(select(CatalogRevisionAssembly).where(
                CatalogRevisionAssembly.revision_id == binding.revision_id)
                .order_by(CatalogRevisionAssembly.sort_order, CatalogRevisionAssembly.id)):
            sid = f"CBR{binding.revision_id}A{assembly.id}"
            diagrams = repository.diagrams_for_source(db, sid)
            assemblies.append({
                "source_id": sid, "family": catalog_code,
                "assembly": assembly.name_bg, "title": assembly.name_bg,
                "name_bg": assembly.name_bg, "name_en": assembly.name_en, "name_ru": assembly.name_ru,
                "document_reference": None,
                "part_count": len(repository.parts_for_source(db, sid, builder_revision_id=binding.revision_id)),
                "diagram_count": len(diagrams),
                "verified_hotspot_count": repository.verified_hotspot_count(db, sid),
                "diagrams": [serialize_diagram(x) for x in diagrams],
            })
        return {**base, "dataset_version": f"CATALOG_BUILDER_R{binding.revision_id}",
                "supported": True, "message": "Публикуван каталог.",
                "family": catalog_code, "assemblies": assemblies}
    if family is None or not asset_supports(machine, "HAS_PARTS_CATALOG"):
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
    if not asset_supports(machine, "HAS_PARTS_CATALOG"):
        raise ApplicationError(
            status_code=409, code="workflow_not_supported",
            message="Категорията не поддържа структуриран каталог.",
            operation="catalog_read", stage="capability",
        )
    binding = published_binding(db, machine)
    if binding is not None:
        assembly = _builder_assembly(db, binding.revision_id, source_id)
        if assembly is None:
            raise ApplicationError(status_code=409, code="catalog_runtime_binding_mismatch",
                                   message="Каталожният възел не принадлежи към машината.",
                                   operation="catalog_read", stage="compatibility")
        _builder_integrity(db, binding.revision_id)
        return machine, {"builder_revision_id": binding.revision_id,
                         "source_id": source_id, "family": db.get(CatalogDefinition, binding.catalog_id).code,
                         "assembly": assembly.name_bg, "document_title": assembly.name_bg,
                         "name_bg": assembly.name_bg, "name_en": assembly.name_en,
                         "name_ru": assembly.name_ru}
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
        "dataset_version": f"CATALOG_BUILDER_R{source['builder_revision_id']}" if source.get("builder_revision_id") else CATALOG_VERSION,
        "machine_id": machine.id,
        "machine_number": str(machine.inventory_number),
        "family": source["family"],
        "source_id": source_id,
        "assembly": source["assembly"],
        "title": source["document_title"],
        "name_bg": source.get("name_bg"), "name_en": source.get("name_en"),
        "name_ru": source.get("name_ru"),
        "diagrams": [
            serialize_diagram(diagram)
            for diagram in repository.diagrams_for_source(db, source_id)
        ],
        "parts": [
            serialize_part(part) for part in repository.parts_for_source(
                db, source_id, builder_revision_id=source.get("builder_revision_id"))
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
    binding = published_binding(db, machine)
    if binding is not None:
        if not asset_supports(machine, "HAS_PARTS_CATALOG"):
            return []
        _builder_integrity(db, binding.revision_id)
        if source_id:
            require_compatible_source(db, machine_id=machine_id, source_id=source_id)
        return [serialize_part(part) for part in repository.search_parts(
            db, query=query, family=db.get(CatalogDefinition, binding.catalog_id).code,
            source_id=source_id, limit=limit, builder_revision_id=binding.revision_id)]
    family = machine_family(machine)
    if family is None or not asset_supports(machine, "HAS_PARTS_CATALOG"):
        return []
    if source_id:
        require_compatible_source(db, machine_id=machine_id, source_id=source_id)
    else:
        for source in dataset_sources():
            if source.get("family") == family and source.get("records_file"):
                ensure_integrity(source["source_id"])
    try:
        translated_source_record_keys = matching_source_record_keys(query)
    except CatalogTranslationError as exc:
        raise _translation_error(exc) from exc
    return [
        serialize_part(part)
        for part in repository.search_parts(
            db,
            query=query,
            family=family,
            source_id=source_id,
            translated_source_record_keys=translated_source_record_keys,
            limit=limit,
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
    _, source = require_compatible_source(db, machine_id=machine_id, source_id=diagram.source_id)
    if diagram.builder_revision_id != source.get("builder_revision_id"):
        if diagram.builder_revision_id is not None or source.get("builder_revision_id") is not None:
            raise ApplicationError(status_code=409, code="catalog_runtime_revision_mismatch",
                                   message="Схемата не принадлежи към текущата ревизия.",
                                   operation="catalog_read", stage="compatibility")
    variants = repository.parts_for_source(db, diagram.source_id,
                                           builder_revision_id=source.get("builder_revision_id"))
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
            "verified_at": hotspot.verified_at,
            "variants": [
                serialize_part(part) for part in by_position.get(hotspot.position, [])
            ],
        }
        for hotspot in repository.hotspots_for_diagram(
            db, diagram_id, verified_only=verified_only
        )
    ]


def mapping_coverage() -> dict[str, Any]:
    return json.loads(
        (CATALOG_ROOT / "position_mapping_report.json").read_text(encoding="utf-8")
    )


def _serialize_kit_component(component: Any) -> dict[str, Any]:
    if component.part.builder_revision_id is not None:
        translation = {"description_en": component.part.name_en or component.part.description,
                       "description_bg": component.part.name_bg or component.part.description,
                       "qa_status": "BUILDER_SOURCE"}
        translation_version = "BUILDER"
    else:
        try:
            translation = translation_for(component.source_record_key)
        except CatalogTranslationError as exc:
            raise _translation_error(exc) from exc
        translation_version = TRANSLATION_VERSION
    return {
        "id": component.id,
        "part_id": component.part_id,
        "source_record_key": component.source_record_key,
        "position": component.part.position,
        "part_number": component.part.part_number,
        "description": component.part.description,
        "source_description": component.part.original_name
        or component.part.description,
        "description_en": translation["description_en"],
        "description_bg": translation["description_bg"],
        "quantity": component.quantity,
        "quantity_raw": component.quantity_raw or "",
        "source_document": component.source_document,
        "source_page": component.source_page,
        "translation_version": translation_version,
        "translation_qa_status": translation["qa_status"],
    }


def serialize_kit(kit: RepairKit) -> dict[str, Any]:
    return {
        "id": kit.id,
        "code": kit.code,
        "name": kit.name,
        "name_bg": kit.name_bg, "name_en": kit.name_en, "name_ru": kit.name_ru,
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
            _serialize_kit_component(component)
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
    binding = published_binding(db, machine)
    if binding is not None:
        if not asset_supports(machine, "HAS_PARTS_CATALOG"):
            return []
        _builder_integrity(db, binding.revision_id)
        if source_id:
            require_compatible_source(db, machine_id=machine_id, source_id=source_id)
        return [serialize_kit(kit) for kit in repository.repair_kits(
            db, family=db.get(CatalogDefinition, binding.catalog_id).code,
            source_id=source_id, builder_revision_id=binding.revision_id)]
    family = machine_family(machine)
    if family is None or not asset_supports(machine, "HAS_PARTS_CATALOG"):
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
