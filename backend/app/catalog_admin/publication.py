"""Atomic boundary between the Builder control plane and the live catalog."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

import fitz
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..models import (
    AssetCategory,
    CatalogAssetBinding,
    CatalogDefinition,
    CatalogDiagram,
    CatalogPositionHotspot,
    CatalogRevision,
    CatalogRevisionArtifact,
    CatalogRevisionAssembly,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
    CatalogRevisionPositionHotspot,
    CatalogRevisionRepairKit,
    CatalogRevisionRepairKitComponent,
    CatalogRevisionVisualPage,
    CatalogVisualPartMap,
    CatalogVisualSource,
    PartCatalog,
    RepairKit,
    RepairKitComponent,
    TechnicalDocument,
    TechnicalDocumentRevision,
    User,
    utcnow,
)
from .service import fail, revision_dict
from .visual_sources import MAX_PDF_PAGES, ROLES


def source_id(assembly: CatalogRevisionAssembly) -> str:
    return f"CBR{assembly.revision_id}A{assembly.id}"


def source_version(revision: CatalogRevision) -> str:
    return f"CATALOG_BUILDER_R{revision.id}"


def _rows(db: Session, model, column, values) -> list:
    ids = list(values)
    return list(db.scalars(select(model).where(column.in_(ids)).order_by(model.id)).all()) if ids else []


def graph(db: Session, revision: CatalogRevision) -> dict:
    assemblies = _rows(db, CatalogRevisionAssembly, CatalogRevisionAssembly.revision_id, [revision.id])
    artifacts = _rows(db, CatalogRevisionArtifact, CatalogRevisionArtifact.assembly_id, [x.id for x in assemblies])
    pages = _rows(db, CatalogRevisionVisualPage, CatalogRevisionVisualPage.artifact_id, [x.id for x in artifacts])
    parts = _rows(db, CatalogRevisionPart, CatalogRevisionPart.assembly_id, [x.id for x in assemblies])
    maps = _rows(db, CatalogRevisionPartPageMap, CatalogRevisionPartPageMap.part_id, [x.id for x in parts])
    hotspots = _rows(db, CatalogRevisionPositionHotspot, CatalogRevisionPositionHotspot.visual_page_id, [x.id for x in pages])
    kits = _rows(db, CatalogRevisionRepairKit, CatalogRevisionRepairKit.assembly_id, [x.id for x in assemblies])
    components = _rows(db, CatalogRevisionRepairKitComponent, CatalogRevisionRepairKitComponent.kit_id, [x.id for x in kits])
    return dict(assemblies=assemblies, artifacts=artifacts, pages=pages, parts=parts,
                maps=maps, hotspots=hotspots, kits=kits, components=components)


PUBLISH_FIELDS = {
    "assemblies": ("id", "revision_id", "code", "name_bg", "name_en", "name_ru", "description", "sort_order"),
    "artifacts": ("id", "assembly_id", "title", "filename", "media_type", "sha256", "page_count", "document_reference", "document_date", "language"),
    "pages": ("id", "artifact_id", "page_number", "role"),
    "parts": ("id", "assembly_id", "position", "part_number", "name_bg", "name_en", "name_ru", "description", "description_2", "quantity", "quantity_raw", "unit", "manufacturer", "category", "replaced_by_part_number", "alternative_part_number", "technical_specification", "technical_notes", "supplier", "supplier_code", "sort_order"),
    "maps": ("id", "part_id", "visual_page_id"),
    "hotspots": ("id", "visual_page_id", "position", "x", "y", "width", "height", "provenance", "is_verified", "verified_by_id", "verified_at", "version"),
    "kits": ("id", "assembly_id", "code", "name_bg", "name_en", "name_ru", "description", "source_visual_page_id", "sort_order"),
    "components": ("id", "kit_id", "part_id", "quantity", "quantity_raw", "is_optional", "note", "sort_order"),
}


def _value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    return value


def digest(catalog: CatalogDefinition, revision: CatalogRevision, content: dict) -> str:
    payload = {
        "catalog": {key: _value(getattr(catalog, key)) for key in
                    ("id", "code", "asset_category_id", "name_bg", "name_en", "name_ru", "description", "manufacturer", "model_reference", "is_active")},
        "revision": {"id": revision.id, "catalog_id": revision.catalog_id, "revision_code": revision.revision_code},
        **{kind: [{key: _value(getattr(row, key)) for key in fields} for row in content[kind]]
           for kind, fields in PUBLISH_FIELDS.items()},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _error(code: str, **ids) -> dict:
    return {"code": code, **ids}


def readiness(db: Session, revision_id: int, *, locked: bool = False) -> dict:
    revision = db.get(CatalogRevision, revision_id)
    if revision is None:
        raise fail("catalog_revision_not_found", 404)
    catalog = db.get(CatalogDefinition, revision.catalog_id)
    if catalog is None:
        raise fail("catalog_definition_not_found", 404)
    if locked:
        catalog = db.scalar(select(CatalogDefinition).where(CatalogDefinition.id == catalog.id)
                            .with_for_update().execution_options(populate_existing=True))
        revision = db.scalar(select(CatalogRevision).where(CatalogRevision.id == revision_id)
                             .with_for_update().execution_options(populate_existing=True))
    current = db.scalar(select(CatalogRevision).where(CatalogRevision.catalog_id == catalog.id,
                                                       CatalogRevision.status == "PUBLISHED"))
    content = graph(db, revision)
    errors, warnings = [], []
    category_query = select(AssetCategory).where(AssetCategory.id == catalog.asset_category_id)
    if locked and db.get_bind().dialect.name == "postgresql":
        category_query = category_query.with_for_update(read=True)
    category = db.scalar(category_query.execution_options(populate_existing=True))
    if not catalog.is_active:
        errors.append(_error("catalog_inactive"))
    if category is None or not category.is_active or "HAS_PARTS_CATALOG" not in (category.capabilities or []):
        errors.append(_error("catalog_category_not_supported"))
    if revision.status != "DRAFT":
        errors.append(_error("catalog_revision_not_draft"))
    if not content["assemblies"]:
        errors.append(_error("catalog_publication_no_assemblies"))
    assembly_by_id = {x.id: x for x in content["assemblies"]}
    artifact_by_id = {x.id: x for x in content["artifacts"]}
    page_by_id = {x.id: x for x in content["pages"]}
    part_by_id = {x.id: x for x in content["parts"]}
    kit_by_id = {x.id: x for x in content["kits"]}
    mapped = defaultdict(list)
    for item in content["maps"]:
        part, page = part_by_id.get(item.part_id), page_by_id.get(item.visual_page_id)
        artifact = artifact_by_id.get(page.artifact_id) if page else None
        if part is None or artifact is None or artifact.assembly_id != part.assembly_id or page.role != "SPARE_PARTS_LIST":
            errors.append(_error("catalog_publication_part_mapping_invalid", mapping_id=item.id))
        else:
            mapped[part.id].append(page)
    for artifact in content["artifacts"]:
        try:
            raw = artifact.content
            if (artifact.media_type != "application/pdf" or not raw.startswith(b"%PDF-")
                    or hashlib.sha256(raw).hexdigest() != artifact.sha256):
                raise ValueError("hash or media type")
            with fitz.open(stream=raw, filetype="pdf") as pdf:
                if pdf.needs_pass or pdf.is_repaired or not 1 <= pdf.page_count <= MAX_PDF_PAGES or pdf.page_count != artifact.page_count:
                    raise ValueError("invalid PDF")
                if any(not all(math.isfinite(v) for v in (page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1))
                       or page.rect.width <= 0 or page.rect.height <= 0 for page in pdf):
                    raise ValueError("invalid page")
        except Exception:
            errors.append(_error("catalog_publication_source_invalid", artifact_id=artifact.id))
    for page in content["pages"]:
        artifact = artifact_by_id.get(page.artifact_id)
        if artifact is None or page.role not in ROLES or not 1 <= page.page_number <= artifact.page_count:
            errors.append(_error("catalog_publication_visual_page_invalid", visual_page_id=page.id))
    positions = defaultdict(set)
    for part in content["parts"]:
        positions[part.assembly_id].add(part.position)
        if (part.assembly_id not in assembly_by_id or not part.position.strip()
                or len(part.position) > 80 or not part.part_number.strip()
                or not any((part.name_bg, part.name_en, part.name_ru, part.description))
                or part.quantity is not None and part.quantity < 0 or not mapped[part.id]):
            errors.append(_error("catalog_publication_part_incomplete", part_id=part.id))
    hotspot_positions = defaultdict(set)
    for hotspot in content["hotspots"]:
        page = page_by_id.get(hotspot.visual_page_id)
        artifact = artifact_by_id.get(page.artifact_id) if page else None
        geometry = (hotspot.x, hotspot.y, hotspot.width, hotspot.height)
        if (artifact is None or page.role != "EXPLODED_SCHEME"
                or hotspot.position not in positions[artifact.assembly_id]
                or not all(math.isfinite(value) for value in geometry)
                or not 0 <= hotspot.x <= 1 or not 0 <= hotspot.y <= 1
                or hotspot.width < .002 or hotspot.height < .002
                or hotspot.x + hotspot.width > 1 or hotspot.y + hotspot.height > 1):
            errors.append(_error("catalog_publication_hotspot_invalid", hotspot_id=hotspot.id))
        elif not hotspot.is_verified or hotspot.verified_by_id is None or hotspot.verified_at is None:
            errors.append(_error("catalog_publication_hotspot_unverified", hotspot_id=hotspot.id))
        else:
            hotspot_positions[artifact.assembly_id].add(hotspot.position)
    for assembly_id, values in positions.items():
        if values - hotspot_positions[assembly_id]:
            warnings.append(_error("catalog_publication_hotspot_coverage", assembly_id=assembly_id,
                                   missing_positions=len(values - hotspot_positions[assembly_id])))
    components_by_kit = defaultdict(list)
    for component in content["components"]:
        components_by_kit[component.kit_id].append(component)
        kit, part = kit_by_id.get(component.kit_id), part_by_id.get(component.part_id)
        if (kit is None or part is None or kit.assembly_id != part.assembly_id
                or component.quantity <= 0 or not mapped[part.id]):
            errors.append(_error("catalog_publication_kit_incomplete", component_id=component.id))
    for kit in content["kits"]:
        source = page_by_id.get(kit.source_visual_page_id) if kit.source_visual_page_id else None
        artifact = artifact_by_id.get(source.artifact_id) if source else None
        if (not kit.code.strip() or not any((kit.name_bg, kit.name_en, kit.name_ru, kit.description))
                or not components_by_kit[kit.id]
                or kit.source_visual_page_id is not None and
                (artifact is None or artifact.assembly_id != kit.assembly_id or source.role != "SPARE_PARTS_LIST")):
            errors.append(_error("catalog_publication_kit_incomplete", kit_id=kit.id))
    summary = {
        "assembly_count": len(content["assemblies"]), "artifact_count": len(content["artifacts"]),
        "part_count": len(content["parts"]), "mapped_part_count": sum(bool(values) for values in mapped.values()),
        "exploded_page_count": sum(x.role == "EXPLODED_SCHEME" for x in content["pages"]),
        "spare_list_page_count": sum(x.role == "SPARE_PARTS_LIST" for x in content["pages"]),
        "hotspot_count": len(content["hotspots"]),
        "verified_hotspot_count": sum(x.is_verified for x in content["hotspots"]),
        "repair_kit_count": len(content["kits"]),
        "repair_kit_component_count": len(content["components"]),
    }
    return {"ready": not errors, "errors": errors, "warnings": warnings,
            "publication_digest": digest(catalog, revision, content),
            "current_published_revision_id": current.id if current else None,
            "summary": summary}


def _materialize(db: Session, actor: User, catalog: CatalogDefinition,
                 revision: CatalogRevision, content: dict) -> None:
    version = source_version(revision)
    assemblies = {row.id: row for row in content["assemblies"]}
    artifacts = {row.id: row for row in content["artifacts"]}
    pages = {row.id: row for row in content["pages"]}
    documents = {}
    for artifact in content["artifacts"]:
        document = TechnicalDocument(
            builder_artifact_id=artifact.id, brand="", category="CATALOG_BUILDER",
            title=artifact.title, file_path=f"catalog-builder/{artifact.id}/{artifact.sha256}",
            source_id=f"CBA{artifact.id}", dataset_version=version,
            revision=revision.revision_code, source_label=artifact.document_reference,
            document_date=datetime.combine(artifact.document_date, datetime.min.time()) if artifact.document_date else None,
            language=artifact.language if artifact.language in {"bg", "en", "ru"} else None,
            page_count=artifact.page_count, sha256=artifact.sha256,
            uploaded_content=artifact.content, uploaded_filename=artifact.filename,
            media_type=artifact.media_type, uploaded_by_id=actor.id,
        )
        db.add(document)
        db.flush()
        db.add(TechnicalDocumentRevision(document_id=document.id, version=1,
                                         revision_label=revision.revision_code, filename=artifact.filename,
                                         media_type=artifact.media_type, content=artifact.content,
                                         sha256=artifact.sha256, created_by_id=actor.id))
        documents[artifact.id] = document
    visuals = {}
    diagrams = {}
    for page in content["pages"]:
        artifact = artifacts[page.artifact_id]
        assembly = assemblies[artifact.assembly_id]
        sid = source_id(assembly)
        visual = CatalogVisualSource(
            builder_revision_id=revision.id, builder_visual_page_id=page.id,
            source_id=sid, catalog_revision=version, technical_document_id=documents[artifact.id].id,
            page_number=page.page_number, role=page.role, source_sha256=artifact.sha256,
        )
        db.add(visual)
        db.flush()
        visuals[page.id] = visual
        if page.role == "EXPLODED_SCHEME":
            diagram = CatalogDiagram(
                builder_revision_id=revision.id, builder_visual_page_id=page.id,
                source_id=sid, family=catalog.code, assembly=assembly.code,
                technical_document_id=documents[artifact.id].id, page_number=page.page_number,
                title=f"{assembly.name_bg} — {artifact.title}", source_pdf_sha256=artifact.sha256,
            )
            db.add(diagram)
            db.flush()
            diagrams[page.id] = diagram
    first_maps = {}
    for mapping in content["maps"]:
        first_maps.setdefault(mapping.part_id, mapping)
    parts = {}
    for item in content["parts"]:
        assembly = assemblies[item.assembly_id]
        mapping = first_maps[item.id]
        page = pages[mapping.visual_page_id]
        artifact = artifacts[page.artifact_id]
        part = PartCatalog(
            builder_revision_id=revision.id, builder_part_id=item.id,
            source_record_key=f"CBP{item.id}", source_id=source_id(assembly),
            source_row_index=item.sort_order, family=catalog.code, brand="", model="",
            assembly=assembly.name_bg, position=item.position, part_number=item.part_number,
            description=item.description or item.name_bg or item.name_en or item.name_ru,
            description_2=item.description_2, quantity=float(item.quantity) if item.quantity is not None else None,
            quantity_raw=item.quantity_raw, name_bg=item.name_bg, name_en=item.name_en,
            name_ru=item.name_ru, original_name=item.name_en or item.name_bg or item.name_ru,
            unit=item.unit, manufacturer=item.manufacturer, category=item.category,
            replaced_by_part_number=item.replaced_by_part_number,
            alternative_part_number=item.alternative_part_number,
            technical_specification=item.technical_specification,
            technical_notes=item.technical_notes, supplier=item.supplier,
            supplier_code=item.supplier_code, source_document=artifact.filename,
            source_page=page.page_number, source_version=version,
            source_document_sha256=artifact.sha256, revision=revision.revision_code,
            verification_status="VERIFIED_BUILDER_PUBLICATION", is_active=True,
            is_verified=True, verified_by_id=actor.id, verified_at=utcnow(),
        )
        db.add(part)
        db.flush()
        parts[item.id] = part
    for mapping in content["maps"]:
        db.add(CatalogVisualPartMap(builder_part_page_map_id=mapping.id,
                                    visual_source_id=visuals[mapping.visual_page_id].id,
                                    part_id=parts[mapping.part_id].id))
    for item in content["hotspots"]:
        db.add(CatalogPositionHotspot(
            builder_revision_id=revision.id, builder_hotspot_id=item.id,
            hotspot_key=f"CBH{item.id}", diagram_id=diagrams[item.visual_page_id].id,
            position=item.position, x=item.x, y=item.y, width=item.width, height=item.height,
            provenance=item.provenance, confidence=1.0, is_verified=True,
            verified_by_id=item.verified_by_id, verified_at=item.verified_at,
            created_by_id=actor.id,
        ))
    kits = {}
    for item in content["kits"]:
        assembly = assemblies[item.assembly_id]
        page = pages.get(item.source_visual_page_id)
        artifact = artifacts[page.artifact_id] if page else None
        kit = RepairKit(
            builder_revision_id=revision.id, builder_kit_id=item.id, code=item.code,
            name=item.name_bg or item.name_en or item.name_ru or item.description,
            name_bg=item.name_bg, name_en=item.name_en, name_ru=item.name_ru,
            family=catalog.code, source_id=source_id(assembly), source_version=version,
            source_document_sha256=artifact.sha256 if artifact else None,
            brand="", model="", revision=revision.revision_code,
            assembly=assembly.name_bg, source_document=artifact.filename if artifact else None,
            source_page=page.page_number if page else None,
            provenance="BUILDER_VERIFIED", confidence=1.0, is_approved=True,
            is_active=True, approved_by_id=actor.id, approved_at=utcnow(), created_by_id=actor.id,
        )
        db.add(kit)
        db.flush()
        kits[item.id] = kit
    for item in content["components"]:
        part = parts[item.part_id]
        db.add(RepairKitComponent(
            builder_component_id=item.id, kit_id=kits[item.kit_id].id, part_id=part.id,
            quantity=float(item.quantity), quantity_raw=item.quantity_raw,
            source_record_key=part.source_record_key, source_document=part.source_document,
            source_page=part.source_page, is_optional=item.is_optional, note=item.note,
        ))
    db.flush()


def publish(db: Session, actor: User, revision_id: int, expected_digest: str,
            expected_current_id: int | None, confirmed: bool) -> dict:
    if not confirmed:
        raise fail("catalog_publication_confirmation_required", 422)
    try:
        result = readiness(db, revision_id, locked=True)
        revision = db.get(CatalogRevision, revision_id)
        catalog = db.get(CatalogDefinition, revision.catalog_id)
        if (expected_digest != result["publication_digest"]
                or expected_current_id != result["current_published_revision_id"]):
            raise fail("catalog_publication_stale")
        if revision.status != "DRAFT":
            raise fail("catalog_revision_not_draft")
        if not result["ready"]:
            raise fail("catalog_publication_not_ready")
        old = db.get(CatalogRevision, result["current_published_revision_id"]) if result["current_published_revision_id"] else None
        content = graph(db, revision)
        _materialize(db, actor, catalog, revision, content)
        if old is not None:
            for part in db.scalars(select(PartCatalog).where(PartCatalog.builder_revision_id == old.id)):
                part.is_active = False
            for kit in db.scalars(select(RepairKit).where(RepairKit.builder_revision_id == old.id)):
                kit.is_active = False
            old.status = "RETIRED"
            old.updated_at = utcnow()
            add_audit_log(db, actor, "catalog_revision", old.id, "CATALOG_REVISION_RETIRED",
                          {"catalog_code": catalog.code, "revision_code": old.revision_code,
                           "successor_revision_id": revision.id})
        revision.status = "PUBLISHED"
        revision.published_by_id = actor.id
        revision.published_at = utcnow()
        revision.updated_at = utcnow()
        add_audit_log(db, actor, "catalog_revision", revision.id, "CATALOG_PUBLICATION_VALIDATED",
                      {"catalog_code": catalog.code, "revision_code": revision.revision_code,
                       "digest": result["publication_digest"], **result["summary"]})
        add_audit_log(db, actor, "catalog_revision", revision.id, "CATALOG_REVISION_PUBLISHED",
                      {"catalog_code": catalog.code, "revision_code": revision.revision_code,
                       "previous_revision_id": old.id if old else None,
                       "digest": result["publication_digest"], **result["summary"],
                       "bound_asset_count": len(db.scalars(select(CatalogAssetBinding.id).where(
                           CatalogAssetBinding.catalog_id == catalog.id)).all()), "publisher_id": actor.id})
        db.commit()
        return revision_dict(revision)
    except IntegrityError as exc:
        db.rollback()
        raise fail("catalog_publication_conflict") from exc
    except Exception:
        db.rollback()
        raise


def clone(db: Session, actor: User, revision_id: int,
          revision_code: str, change_note: str | None) -> dict:
    """Copy the complete published graph into an independent draft."""
    source = db.get(CatalogRevision, revision_id)
    if source is None:
        raise fail("catalog_revision_not_found", 404)
    try:
        catalog = db.scalar(select(CatalogDefinition).where(CatalogDefinition.id == source.catalog_id)
                            .with_for_update().execution_options(populate_existing=True))
        source = db.scalar(select(CatalogRevision).where(CatalogRevision.id == revision_id)
                           .with_for_update().execution_options(populate_existing=True))
        if source.status != "PUBLISHED" or not catalog.is_active:
            raise fail("catalog_clone_invalid")
        content = graph(db, source)
        target = CatalogRevision(catalog_id=catalog.id, revision_code=revision_code,
                                 status="DRAFT", change_note=change_note, created_by_id=actor.id)
        db.add(target)
        db.flush()
        assembly_ids, artifact_ids, page_ids, part_ids, kit_ids = {}, {}, {}, {}, {}
        for item in content["assemblies"]:
            values = {key: getattr(item, key) for key in PUBLISH_FIELDS["assemblies"]
                      if key not in {"id", "revision_id"}}
            new = CatalogRevisionAssembly(revision_id=target.id, created_by_id=actor.id, **values)
            db.add(new)
            db.flush()
            assembly_ids[item.id] = new.id
        for item in content["artifacts"]:
            values = {key: getattr(item, key) for key in PUBLISH_FIELDS["artifacts"]
                      if key not in {"id", "assembly_id"}}
            new = CatalogRevisionArtifact(assembly_id=assembly_ids[item.assembly_id],
                                          content=item.content, created_by_id=actor.id, **values)
            db.add(new)
            db.flush()
            artifact_ids[item.id] = new.id
        for item in content["pages"]:
            new = CatalogRevisionVisualPage(artifact_id=artifact_ids[item.artifact_id],
                                            page_number=item.page_number, role=item.role,
                                            created_by_id=actor.id)
            db.add(new)
            db.flush()
            page_ids[item.id] = new.id
        for item in content["parts"]:
            values = {key: getattr(item, key) for key in PUBLISH_FIELDS["parts"]
                      if key not in {"id", "assembly_id"}}
            new = CatalogRevisionPart(assembly_id=assembly_ids[item.assembly_id],
                                      created_by_id=actor.id, **values)
            db.add(new)
            db.flush()
            part_ids[item.id] = new.id
        for item in content["maps"]:
            db.add(CatalogRevisionPartPageMap(part_id=part_ids[item.part_id],
                                              visual_page_id=page_ids[item.visual_page_id],
                                              created_by_id=actor.id))
        for item in content["hotspots"]:
            db.add(CatalogRevisionPositionHotspot(
                visual_page_id=page_ids[item.visual_page_id], position=item.position,
                x=item.x, y=item.y, width=item.width, height=item.height,
                provenance="INHERITED_VERIFICATION" if item.is_verified else item.provenance,
                is_verified=item.is_verified, verified_by_id=item.verified_by_id,
                verified_at=item.verified_at, version=1, created_by_id=actor.id,
            ))
        kits_with_components = {item.kit_id for item in content["components"]}
        for item in content["kits"]:
            values = {key: getattr(item, key) for key in PUBLISH_FIELDS["kits"]
                      if key not in {"id", "assembly_id", "source_visual_page_id"}}
            new = CatalogRevisionRepairKit(
                assembly_id=assembly_ids[item.assembly_id],
                source_visual_page_id=page_ids.get(item.source_visual_page_id),
                code_locked=item.code_locked or item.id in kits_with_components,
                created_by_id=actor.id, **values,
            )
            db.add(new)
            db.flush()
            kit_ids[item.id] = new.id
        for item in content["components"]:
            values = {key: getattr(item, key) for key in PUBLISH_FIELDS["components"]
                      if key not in {"id", "kit_id", "part_id"}}
            db.add(CatalogRevisionRepairKitComponent(
                kit_id=kit_ids[item.kit_id], part_id=part_ids[item.part_id],
                created_by_id=actor.id, **values,
            ))
        db.flush()
        add_audit_log(db, actor, "catalog_revision", target.id, "CATALOG_REVISION_CLONED",
                      {"catalog_code": catalog.code, "source_revision_id": source.id,
                       "target_revision_code": revision_code,
                       **{key[:-1] + "_count": len(rows) for key, rows in content.items()}})
        db.commit()
        return revision_dict(target)
    except IntegrityError as exc:
        db.rollback()
        raise fail("catalog_clone_invalid") from exc
    except Exception:
        db.rollback()
        raise
