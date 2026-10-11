"""Draft-only Builder visual sources. No runtime catalog model is imported here."""

from __future__ import annotations

import base64
import binascii
import hashlib

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..models import (
    CatalogDefinition,
    CatalogRevision,
    CatalogRevisionArtifact,
    CatalogRevisionAssembly,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
    CatalogRevisionPositionHotspot,
    CatalogRevisionReferencePage,
    CatalogRevisionRepairKit,
    CatalogRevisionRepairKitComponent,
    CatalogRevisionVisualPage,
    User,
    utcnow,
)
from ..settings import settings
from . import source_storage
from .schemas import ArtifactUpload, AssemblyCreate, AssemblyUpdate, VisualPageCreate
from .service import fail

MAX_PDF_BYTES = settings.catalog_pdf_max_bytes
MAX_PDF_PAGES = settings.catalog_pdf_max_pages
ROLES = {"EXPLODED_SCHEME", "SPARE_PARTS_LIST"}


def lock_catalog(db: Session, catalog_id: int):
    db.flush()
    # SQLite ignores FOR UPDATE. Acquire its write lock before authoritative reads.
    # PostgreSQL serializes all Builder mutations/publication on the catalog row.
    if db.get_bind().dialect.name == "sqlite":
        db.execute(update(CatalogDefinition).where(CatalogDefinition.id == catalog_id)
                   .values(id=catalog_id, updated_at=CatalogDefinition.updated_at)
                   .execution_options(synchronize_session=False))
    catalog = db.scalar(select(CatalogDefinition).where(CatalogDefinition.id == catalog_id)
        .with_for_update().execution_options(populate_existing=True))
    # A long-lived ORM session may have read the graph before waiting for this
    # lock. The explicit flush preserves local writes with autoflush disabled;
    # reread cached rows afterwards.
    db.expire_all()
    return catalog


def _revision(db: Session, revision_id: int, *, mutate: bool = False):
    revision = db.scalar(select(CatalogRevision).where(CatalogRevision.id == revision_id))
    if revision is None:
        raise fail("catalog_revision_not_found", 404)
    catalog_query = select(CatalogDefinition).where(CatalogDefinition.id == revision.catalog_id)
    catalog = lock_catalog(db, revision.catalog_id) if mutate else db.scalar(catalog_query)
    if catalog is None:
        raise fail("catalog_definition_not_found", 404)
    if mutate:
        revision = db.scalar(select(CatalogRevision).where(CatalogRevision.id == revision_id)
                             .with_for_update().execution_options(populate_existing=True))
        if revision is None or revision.catalog_id != catalog.id:
            raise fail("catalog_revision_not_found", 404)
        if revision.status != "DRAFT":
            raise fail("catalog_revision_not_draft")
        if not catalog.is_active:
            raise fail("catalog_inactive")
    return revision, catalog


def _assembly(db: Session, assembly_id: int, *, mutate: bool = False):
    assembly = db.get(CatalogRevisionAssembly, assembly_id)
    if assembly is None:
        raise fail("catalog_assembly_not_found", 404)
    revision, catalog = _revision(db, assembly.revision_id, mutate=mutate)
    if mutate:
        assembly = db.scalar(select(CatalogRevisionAssembly).where(CatalogRevisionAssembly.id == assembly_id)
                             .execution_options(populate_existing=True))
        if assembly is None or assembly.revision_id != revision.id:
            raise fail("catalog_assembly_not_found", 404)
    return assembly, revision, catalog


def _artifact(db: Session, artifact_id: int, *, mutate: bool = False):
    artifact = db.get(CatalogRevisionArtifact, artifact_id)
    if artifact is None:
        raise fail("catalog_source_not_found", 404)
    assembly, revision, catalog = _assembly(db, artifact.assembly_id, mutate=mutate)
    if mutate:
        artifact = db.scalar(select(CatalogRevisionArtifact).where(CatalogRevisionArtifact.id == artifact_id)
                             .execution_options(populate_existing=True))
        if artifact is None or artifact.assembly_id != assembly.id:
            raise fail("catalog_source_not_found", 404)
    return artifact, assembly, revision, catalog


def _meta(catalog, revision, assembly, artifact=None, **extra):
    result = {"catalog_code": catalog.code, "revision_code": revision.revision_code,
              "assembly_code": assembly.code}
    if artifact is not None:
        result.update({"artifact_id": artifact.id, "filename": artifact.filename, "sha256": artifact.sha256})
    result.update(extra)
    return result


def _role_pages(db: Session, artifact_id: int) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = {role: [] for role in sorted(ROLES)}
    for page in db.scalars(select(CatalogRevisionVisualPage)
                           .where(CatalogRevisionVisualPage.artifact_id == artifact_id)
                           .order_by(CatalogRevisionVisualPage.page_number)).all():
        grouped[page.role].append(page.page_number)
    return grouped


def _assembly_dict(db: Session, item: CatalogRevisionAssembly) -> dict:
    artifacts = db.scalars(select(CatalogRevisionArtifact).where(CatalogRevisionArtifact.assembly_id == item.id)).all()
    ids = [artifact.id for artifact in artifacts]
    counts = {role: 0 for role in ROLES}
    if ids:
        for role, count in db.execute(select(CatalogRevisionVisualPage.role, func.count())
                                      .where(CatalogRevisionVisualPage.artifact_id.in_(ids))
                                      .group_by(CatalogRevisionVisualPage.role)):
            counts[role] = count
    return {"id": item.id, "revision_id": item.revision_id, "code": item.code,
            "name_bg": item.name_bg, "name_en": item.name_en, "name_ru": item.name_ru,
            "description": item.description, "sort_order": item.sort_order,
            "artifact_count": len(artifacts), "exploded_page_count": counts["EXPLODED_SCHEME"],
            "spare_list_page_count": counts["SPARE_PARTS_LIST"],
            "part_count": db.scalar(select(func.count(CatalogRevisionPart.id)).where(
                CatalogRevisionPart.assembly_id == item.id)),
            "hotspot_count": db.scalar(select(func.count(CatalogRevisionPositionHotspot.id)).where(
                CatalogRevisionPositionHotspot.visual_page_id.in_(select(CatalogRevisionVisualPage.id).where(
                    CatalogRevisionVisualPage.artifact_id.in_(select(CatalogRevisionArtifact.id).where(
                        CatalogRevisionArtifact.assembly_id == item.id)))))),
            "repair_kit_count": db.scalar(select(func.count(CatalogRevisionRepairKit.id)).where(
                CatalogRevisionRepairKit.assembly_id == item.id)),
            "repair_kit_component_count": db.scalar(select(func.count(CatalogRevisionRepairKitComponent.id)).where(
                CatalogRevisionRepairKitComponent.kit_id.in_(select(CatalogRevisionRepairKit.id).where(
                    CatalogRevisionRepairKit.assembly_id == item.id))))}


def list_assemblies(db: Session, revision_id: int) -> list[dict]:
    _revision(db, revision_id)
    items = db.scalars(select(CatalogRevisionAssembly).where(CatalogRevisionAssembly.revision_id == revision_id)
                       .order_by(CatalogRevisionAssembly.sort_order, CatalogRevisionAssembly.id)).all()
    return [_assembly_dict(db, item) for item in items]


def create_assembly(db: Session, actor: User, revision_id: int, data: AssemblyCreate, *, commit: bool = True) -> dict:
    revision, catalog = _revision(db, revision_id, mutate=True)
    item = CatalogRevisionAssembly(revision_id=revision.id, created_by_id=actor.id, **data.model_dump())
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise fail("catalog_assembly_duplicate") from exc
    add_audit_log(db, actor, "catalog_revision_assembly", item.id, "ASSEMBLY_CREATED",
                  _meta(catalog, revision, item))
    if commit:
        db.commit()
    return _assembly_dict(db, item)


def update_assembly(db: Session, actor: User, assembly_id: int, data: AssemblyUpdate) -> dict:
    item, revision, catalog = _assembly(db, assembly_id, mutate=True)
    changes = data.model_dump(exclude_unset=True)
    if any(changes.get(key) is None for key in ("code", "name_bg", "name_en", "name_ru", "sort_order") if key in changes):
        raise fail("catalog_assembly_code_immutable", 422)
    if "code" in changes and changes["code"] != item.code:
        if db.scalar(select(CatalogRevisionArtifact.id).where(CatalogRevisionArtifact.assembly_id == item.id).limit(1)):
            raise fail("catalog_assembly_code_in_use")
        raise fail("catalog_assembly_code_immutable")
    before = {key: getattr(item, key) for key in changes}
    for key, value in changes.items():
        setattr(item, key, value)
    if changes:
        item.updated_at = utcnow()
        add_audit_log(db, actor, "catalog_revision_assembly", item.id, "ASSEMBLY_UPDATED",
                      _meta(catalog, revision, item, before=before, after=changes))
    db.commit()
    return _assembly_dict(db, item)


def delete_assembly(db: Session, actor: User, assembly_id: int) -> None:
    from .hotspots import remove_page_hotspots
    from .repair_kits import remove_assembly_kits

    item, revision, catalog = _assembly(db, assembly_id, mutate=True)
    if db.scalar(select(CatalogRevisionReferencePage.id).where(
            CatalogRevisionReferencePage.assembly_id == item.id).limit(1)):
        raise fail("catalog_reference_page_in_use")
    from .parts_extraction import ledger
    if db.scalar(select(ledger.Attempt.id).join(ledger.Source, ledger.Attempt.source_id == ledger.Source.id)
            .join(ledger.ExtractionSession, ledger.Source.session_id == ledger.ExtractionSession.id)
            .join(CatalogRevisionVisualPage, ledger.Source.visual_page_id == CatalogRevisionVisualPage.id)
            .join(CatalogRevisionArtifact, CatalogRevisionVisualPage.artifact_id == CatalogRevisionArtifact.id)
            .where(ledger.ExtractionSession.revision_id == revision.id,
                CatalogRevisionArtifact.assembly_id == item.id).limit(1)):
        raise fail("catalog_source_correction_review_required")
    ledger.invalidate_scope(db, actor, assembly_id, None, "ASSEMBLY_REMOVED")
    artifacts = db.scalars(select(CatalogRevisionArtifact).where(CatalogRevisionArtifact.assembly_id == item.id)).all()
    artifact_audit = [{"artifact_id": artifact.id, "filename": artifact.filename,
                       "sha256": artifact.sha256, "visual_pages": _role_pages(db, artifact.id)}
                      for artifact in artifacts]
    artifact_ids = select(CatalogRevisionArtifact.id).where(CatalogRevisionArtifact.assembly_id == item.id)
    part_ids = select(CatalogRevisionPart.id).where(CatalogRevisionPart.assembly_id == item.id)
    page_ids = select(CatalogRevisionVisualPage.id).where(CatalogRevisionVisualPage.artifact_id.in_(artifact_ids))
    part_count = db.scalar(select(func.count(CatalogRevisionPart.id)).where(CatalogRevisionPart.assembly_id == item.id))
    mapping_count = db.scalar(select(func.count(CatalogRevisionPartPageMap.id)).where(
        CatalogRevisionPartPageMap.part_id.in_(part_ids)))
    kit_counts = remove_assembly_kits(db, item.id)
    hotspot_counts = remove_page_hotspots(db, actor, page_ids, catalog, revision, item)
    add_audit_log(db, actor, "catalog_revision_assembly", item.id, "ASSEMBLY_DELETED",
                  _meta(catalog, revision, item, artifacts=artifact_audit,
                        part_count=part_count, removed_part_page_maps=mapping_count,
                        **kit_counts, **hotspot_counts))
    db.execute(delete(CatalogRevisionPartPageMap).where(CatalogRevisionPartPageMap.part_id.in_(part_ids)))
    db.execute(delete(CatalogRevisionPartPageMap).where(CatalogRevisionPartPageMap.visual_page_id.in_(page_ids)))
    db.execute(delete(CatalogRevisionPart).where(CatalogRevisionPart.assembly_id == item.id))
    db.execute(delete(CatalogRevisionVisualPage).where(CatalogRevisionVisualPage.artifact_id.in_(artifact_ids)))
    db.execute(delete(CatalogRevisionArtifact).where(CatalogRevisionArtifact.assembly_id == item.id))
    db.delete(item)
    db.commit()


def _artifact_dict(item: CatalogRevisionArtifact) -> dict:
    return {"id": item.id, "assembly_id": item.assembly_id, "title": item.title,
            "filename": item.filename, "media_type": item.media_type, "sha256": item.sha256,
            "page_count": item.page_count, "document_reference": item.document_reference,
            "document_date": item.document_date, "language": item.language, "created_at": item.created_at}


def list_artifacts(db: Session, assembly_id: int) -> list[dict]:
    _assembly(db, assembly_id)
    return [_artifact_dict(item) for item in db.scalars(select(CatalogRevisionArtifact)
            .where(CatalogRevisionArtifact.assembly_id == assembly_id)
            .order_by(CatalogRevisionArtifact.id)).all()]


def get_artifact(db: Session, artifact_id: int) -> dict:
    return _artifact_dict(_artifact(db, artifact_id)[0])


def upload_artifact(db: Session, actor: User, assembly_id: int, data: ArtifactUpload) -> dict:
    # Legacy compatibility endpoint. The primary UI uses binary UploadFile.
    if data.media_type != "application/pdf" or not data.filename.lower().endswith(".pdf"):
        raise fail("catalog_source_invalid_pdf", 422)
    if len(data.content_base64) > ((settings.catalog_pdf_max_bytes + 2) // 3) * 4:
        raise fail("catalog_source_too_large", 413)
    try:
        content = base64.b64decode(data.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise fail("catalog_source_invalid_pdf", 422) from exc
    return store_artifact(db, actor, assembly_id, content, data.filename, data.title,
                          document_reference=data.document_reference, document_date=data.document_date,
                          language=data.language)


def store_artifact(db: Session, actor: User, assembly_id: int, content: bytes,
                   filename: str, title: str, **metadata) -> dict:
    assembly, revision, catalog = _assembly(db, assembly_id, mutate=True)
    if (not 1 <= len(filename) <= 255 or not 1 <= len(title.strip()) <= 255
            or any(ch in filename for ch in ("/", "\\", '"'))
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in filename)
            or filename in {".", ".."}):
        raise fail("catalog_source_invalid_pdf", 422)
    page_count = source_storage.validate_pdf(content)
    digest = hashlib.sha256(content).hexdigest()
    existing = db.scalar(select(CatalogRevisionArtifact).where(
        CatalogRevisionArtifact.assembly_id == assembly.id, CatalogRevisionArtifact.sha256 == digest))
    if existing:
        raise HTTPException(409, detail={"code": "catalog_source_duplicate", "artifact_id": existing.id})
    item = CatalogRevisionArtifact(assembly_id=assembly.id, title=title.strip(),
                                   filename=filename, media_type="application/pdf",
                                   source_blob=source_storage.shared_blob(db, content, digest), stored_content=b"",
                                   sha256=digest, page_count=page_count,
                                   created_by_id=actor.id, **metadata)
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(select(CatalogRevisionArtifact).where(
            CatalogRevisionArtifact.assembly_id == assembly_id, CatalogRevisionArtifact.sha256 == digest))
        if existing:
            raise HTTPException(409, detail={"code": "catalog_source_duplicate", "artifact_id": existing.id}) from exc
        raise fail("catalog_source_duplicate") from exc
    add_audit_log(db, actor, "catalog_revision_artifact", item.id, "CATALOG_SOURCE_UPLOADED",
                  _meta(catalog, revision, assembly, item, page_count=page_count))
    db.commit()
    return _artifact_dict(item)


def delete_artifact(db: Session, actor: User, artifact_id: int) -> None:
    from .hotspots import remove_page_hotspots
    from .repair_kits import source_page_reference_count

    item, assembly, revision, catalog = _artifact(db, artifact_id, mutate=True)
    page_ids = select(CatalogRevisionVisualPage.id).where(CatalogRevisionVisualPage.artifact_id == item.id)
    # Explicit logical-page assignments cannot be silently erased via the legacy
    # artifact endpoint. Remove them through their versioned page workflow first.
    if db.scalar(select(CatalogRevisionVisualPage.id).where(
            CatalogRevisionVisualPage.artifact_id == item.id,
            CatalogRevisionVisualPage.reference_page_id.is_not(None)).limit(1)):
        raise fail("catalog_reference_page_in_use")
    if source_page_reference_count(db, page_ids):
        raise fail("catalog_repair_kit_source_page_in_use")
    from .parts_extraction import ledger
    if db.scalar(select(ledger.Attempt.id).join(ledger.Source, ledger.Attempt.source_id == ledger.Source.id)
            .where(ledger.Source.visual_page_id.in_(page_ids)).limit(1)):
        raise fail("catalog_source_correction_review_required")
    ledger.invalidate_scope(db, actor, assembly.id, None, "SOURCE_DOCUMENT_REMOVED")
    mapped = db.execute(select(CatalogRevisionPartPageMap.part_id, CatalogRevisionPartPageMap.visual_page_id)
                        .where(CatalogRevisionPartPageMap.visual_page_id.in_(page_ids))).all()
    hotspot_counts = remove_page_hotspots(db, actor, page_ids, catalog, revision, assembly)
    add_audit_log(db, actor, "catalog_revision_artifact", item.id, "CATALOG_SOURCE_DELETED",
                  _meta(catalog, revision, assembly, item, visual_pages=_role_pages(db, item.id),
                        removed_part_page_maps=[{"part_id": part_id, "visual_page_id": page_id}
                                                for part_id, page_id in mapped], **hotspot_counts))
    db.execute(delete(CatalogRevisionPartPageMap).where(CatalogRevisionPartPageMap.visual_page_id.in_(page_ids)))
    db.execute(delete(CatalogRevisionVisualPage).where(CatalogRevisionVisualPage.artifact_id == item.id))
    db.delete(item)
    db.commit()


def _page_dict(item: CatalogRevisionVisualPage) -> dict:
    return {"id": item.id, "artifact_id": item.artifact_id, "page_number": item.page_number,
            "role": item.role, "reference_page_id": item.reference_page_id, "sort_order": item.sort_order, "created_at": item.created_at}


def list_visual_pages(db: Session, artifact_id: int) -> list[dict]:
    _artifact(db, artifact_id)
    return [_page_dict(item) for item in db.scalars(select(CatalogRevisionVisualPage)
            .where(CatalogRevisionVisualPage.artifact_id == artifact_id)
            .order_by(CatalogRevisionVisualPage.page_number, CatalogRevisionVisualPage.role)).all()]


def assign_visual_pages(db: Session, actor: User, artifact_id: int, data: VisualPageCreate) -> list[dict]:
    item, assembly, revision, catalog = _artifact(db, artifact_id, mutate=True)
    if data.role not in ROLES:
        raise fail("catalog_visual_role_invalid", 422)
    numbers = data.page_numbers
    if len(set(numbers)) != len(numbers) or any(page < 1 or page > item.page_count for page in numbers):
        raise fail("catalog_visual_page_invalid", 422)
    existing = db.scalar(select(CatalogRevisionVisualPage.id).where(
        CatalogRevisionVisualPage.artifact_id == item.id,
        CatalogRevisionVisualPage.page_number.in_(numbers),
        CatalogRevisionVisualPage.role == data.role).limit(1))
    if existing:
        raise fail("catalog_visual_page_duplicate")
    from .parts_extraction.ledger import invalidate_scope
    invalidate_scope(db, actor, assembly.id, None, "SOURCE_ASSIGNMENT_ADDED")
    rows = [CatalogRevisionVisualPage(artifact_id=item.id, page_number=number,
                                      role=data.role, created_by_id=actor.id) for number in numbers]
    db.add_all(rows)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise fail("catalog_visual_page_duplicate") from exc
    add_audit_log(db, actor, "catalog_revision_artifact", item.id, "VISUAL_PAGE_ROLE_ASSIGNED",
                  _meta(catalog, revision, assembly, item, page_numbers=numbers, role=data.role))
    db.commit()
    return [_page_dict(row) for row in rows]


def remove_visual_page(db: Session, actor: User, assignment_id: int, *, reviewed_correction: bool = False) -> None:
    from .hotspots import remove_page_hotspots
    from .repair_kits import source_page_reference_count

    page = db.get(CatalogRevisionVisualPage, assignment_id)
    if page is None:
        raise fail("catalog_visual_page_invalid", 404)
    item, assembly, revision, catalog = _artifact(db, page.artifact_id, mutate=True)
    from .parts_extraction.ledger import invalidate_scope
    invalidate_scope(db, actor, assembly.id, page.reference_page_id, "SOURCE_ASSIGNMENT_REMOVED")
    if page.role == "SPARE_PARTS_LIST" and not reviewed_correction:
        from .parts_extraction import ledger
        attempted = db.scalar(select(ledger.Attempt.id).join(ledger.Source,
            ledger.Attempt.source_id == ledger.Source.id).where(ledger.Source.visual_page_id == page.id).limit(1))
        if attempted:
            raise fail("catalog_source_correction_review_required")
    if page.reference_page_id is not None:
        from .reference_pages import load, sources_in_use, touch
        reference, _, _, _ = load(db, page.reference_page_id, mutate=True)
        if sources_in_use(db, [page.id]):
            raise fail("catalog_reference_source_in_use")
        touch(reference)
    if source_page_reference_count(db, [page.id]):
        raise fail("catalog_repair_kit_source_page_in_use")
    mapped_parts = db.scalars(select(CatalogRevisionPartPageMap.part_id).where(
        CatalogRevisionPartPageMap.visual_page_id == page.id)).all()
    hotspot_counts = remove_page_hotspots(db, actor, [page.id], catalog, revision, assembly)
    add_audit_log(db, actor, "catalog_revision_artifact", item.id, "VISUAL_PAGE_ROLE_REMOVED",
                  _meta(catalog, revision, assembly, item, page_numbers=[page.page_number],
                        role=page.role, unmapped_part_ids=mapped_parts, **hotspot_counts))
    db.execute(delete(CatalogRevisionPartPageMap).where(CatalogRevisionPartPageMap.visual_page_id == page.id))
    db.delete(page)
    db.commit()


def preview_page(db: Session, artifact_id: int, page_number: int, *, thumbnail: bool = False) -> bytes:
    item, _, _, _ = _artifact(db, artifact_id)
    if page_number < 1 or page_number > item.page_count:
        raise fail("catalog_visual_page_invalid", 404)
    from .parts_extraction.process import configuration, extract
    result = extract(item.content, "thumbnail" if thumbnail else "preview", page_number, configuration(settings))
    if result.get("error"):
        raise fail("catalog_source_invalid_pdf", 422)
    return base64.b64decode(result["image"])


def download_artifact(db: Session, artifact_id: int) -> tuple[bytes, str]:
    item = _artifact(db, artifact_id)[0]
    return item.content, item.filename
