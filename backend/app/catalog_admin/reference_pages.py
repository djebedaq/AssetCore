"""Human-defined logical pages, explicitly assigned sources and scoped integrity."""

from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..models import (
    CatalogRevisionArtifact,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
    CatalogRevisionPositionHotspot,
    CatalogRevisionReferencePage,
    CatalogRevisionVisualPage,
    User,
    utcnow,
)
from . import visual_sources
from .service import fail
from .source_storage import shared_blob


def load(db: Session, page_id: int, *, mutate: bool = False):
    page = db.get(CatalogRevisionReferencePage, page_id)
    if page is None:
        raise fail("catalog_reference_page_not_found", 404)
    assembly, revision, catalog = visual_sources._assembly(db, page.assembly_id, mutate=mutate)
    if mutate:
        page = db.scalar(select(CatalogRevisionReferencePage).where(
            CatalogRevisionReferencePage.id == page_id).with_for_update().execution_options(populate_existing=True))
    if page is None or page.assembly_id != assembly.id:
        raise fail("catalog_reference_page_not_found", 404)
    return page, assembly, revision, catalog


def check_version(page, expected: int) -> None:
    if page.version != expected:
        raise fail("catalog_reference_page_stale")


def touch(page) -> None:
    page.version += 1
    page.updated_at = utcnow()


def assignments(db: Session, page_id: int) -> list[dict]:
    rows = db.execute(select(CatalogRevisionVisualPage, CatalogRevisionArtifact).join(
        CatalogRevisionArtifact, CatalogRevisionVisualPage.artifact_id == CatalogRevisionArtifact.id).where(
        CatalogRevisionVisualPage.reference_page_id == page_id).order_by(
        CatalogRevisionVisualPage.sort_order, CatalogRevisionVisualPage.id)).all()
    return [{**visual_sources._page_dict(source), "title": artifact.title,
             "filename": artifact.filename, "sha256": artifact.sha256} for source, artifact in rows]


def serialize(db: Session, page) -> dict:
    sources = assignments(db, page.id)
    positions = set(db.scalars(select(CatalogRevisionPart.position).where(
        CatalogRevisionPart.reference_page_id == page.id)))
    hotspots = db.execute(select(CatalogRevisionPositionHotspot.position,
        CatalogRevisionPositionHotspot.is_verified).join(CatalogRevisionVisualPage,
        CatalogRevisionPositionHotspot.visual_page_id == CatalogRevisionVisualPage.id).where(
        CatalogRevisionVisualPage.reference_page_id == page.id)).all()
    mapped = {position for position, verified in hotspots if verified}
    schemes = sum(source["role"] == "EXPLODED_SCHEME" for source in sources)
    lists = sum(source["role"] == "SPARE_PARTS_LIST" for source in sources)
    count = db.scalar(select(func.count()).select_from(CatalogRevisionPart).where(
        CatalogRevisionPart.reference_page_id == page.id))
    unmapped_parts = db.scalar(select(CatalogRevisionPart.id).where(
        CatalogRevisionPart.reference_page_id == page.id,
        ~select(CatalogRevisionPartPageMap.id).where(
            CatalogRevisionPartPageMap.part_id == CatalogRevisionPart.id).exists()).limit(1))
    complete = bool(schemes and lists and count and unmapped_parts is None
                    and positions <= mapped and all(verified for _, verified in hotspots))
    if complete:
        from ..models import CatalogRevision
        from .parts_extraction import ledger
        assembly, revision, _ = visual_sources._assembly(db, page.assembly_id)
        if revision.status == "DRAFT":
            active = ledger.session(db, None, assembly, db.get(CatalogRevision, assembly.revision_id), page.id)
            reviewed = list(db.scalars(select(ledger.Source).where(ledger.Source.session_id == active.id))) if active else []
            complete = bool(len(reviewed) == lists and all(ledger.valid(db, source, active) for source in reviewed))
    return {"id": page.id, "assembly_id": page.assembly_id, "stable_key": page.stable_key,
            "sort_order": page.sort_order, "title": page.title, "version": page.version,
            "sources": sources, "part_count": count, "position_count": len(positions),
            "mapped_position_count": len(positions & mapped), "scheme_count": schemes,
            "spare_list_count": lists, "status": "COMPLETE" if complete else "NOT_STARTED" if not sources else "NEEDS_ATTENTION"}


def list_pages(db: Session, assembly_id: int) -> list[dict]:
    visual_sources._assembly(db, assembly_id)
    return [serialize(db, page) for page in db.scalars(select(CatalogRevisionReferencePage).where(
        CatalogRevisionReferencePage.assembly_id == assembly_id).order_by(
        CatalogRevisionReferencePage.sort_order, CatalogRevisionReferencePage.id))]


def create(db: Session, actor: User, assembly_id: int, data) -> dict:
    assembly, revision, catalog = visual_sources._assembly(db, assembly_id, mutate=True)
    order = db.scalar(select(func.max(CatalogRevisionReferencePage.sort_order)).where(
        CatalogRevisionReferencePage.assembly_id == assembly.id))
    page = CatalogRevisionReferencePage(assembly_id=assembly.id, stable_key=str(uuid4()),
        sort_order=(order if order is not None else -1) + 1, title=data.title, created_by_id=actor.id)
    db.add(page)
    db.flush()
    add_audit_log(db, actor, "catalog_reference_page", page.id, "REFERENCE_PAGE_CREATED",
        visual_sources._meta(catalog, revision, assembly, stable_key=page.stable_key))
    db.commit()
    return serialize(db, page)


def update(db: Session, actor: User, page_id: int, data) -> dict:
    page, assembly, revision, catalog = load(db, page_id, mutate=True)
    check_version(page, data.expected_version)
    from .parts_extraction.ledger import invalidate_scope
    invalidate_scope(db, actor, assembly.id, page.id, "REFERENCE_PAGE_UPDATED")
    for key, value in data.model_dump(exclude_unset=True, exclude={"expected_version"}).items():
        if key == "sort_order" and value is None:
            raise fail("catalog_invalid_update", 422)
        setattr(page, key, value)
    touch(page)
    add_audit_log(db, actor, "catalog_reference_page", page.id, "REFERENCE_PAGE_UPDATED",
        visual_sources._meta(catalog, revision, assembly, sort_order=page.sort_order, title=page.title))
    db.commit()
    return serialize(db, page)


def delete_page(db: Session, actor: User, page_id: int, expected_version: int) -> None:
    page, assembly, revision, catalog = load(db, page_id, mutate=True)
    check_version(page, expected_version)
    sources = assignments(db, page.id)
    if page_has_dependents(db, page.id):
        raise fail("catalog_reference_page_in_use")
    from .parts_extraction import ledger
    if db.scalar(select(ledger.Attempt.id).join(ledger.Source, ledger.Attempt.source_id == ledger.Source.id)
            .where(ledger.Source.visual_page_id.in_([source["id"] for source in sources])).limit(1)):
        raise fail("catalog_source_correction_review_required")
    ledger.invalidate_scope(db, actor, assembly.id, page.id, "REFERENCE_PAGE_REMOVED")
    for source in sources:
        db.delete(db.get(CatalogRevisionVisualPage, source["id"]))
    add_audit_log(db, actor, "catalog_reference_page", page.id, "REFERENCE_PAGE_DELETED",
        visual_sources._meta(catalog, revision, assembly, stable_key=page.stable_key))
    db.delete(page)
    db.commit()


def page_has_dependents(db: Session, page_id: int) -> bool:
    if db.scalar(select(CatalogRevisionPart.id).where(
            CatalogRevisionPart.reference_page_id == page_id).limit(1)):
        return True
    ids = list(db.scalars(select(CatalogRevisionVisualPage.id).where(
        CatalogRevisionVisualPage.reference_page_id == page_id)))
    return sources_in_use(db, ids)


def sources_in_use(db: Session, ids: list[int]) -> bool:
    from .repair_kits import source_page_reference_count
    return bool(source_page_reference_count(db, ids) or db.scalar(select(CatalogRevisionPartPageMap.id).where(
        CatalogRevisionPartPageMap.visual_page_id.in_(ids)).limit(1)) or db.scalar(select(
        CatalogRevisionPositionHotspot.id).where(CatalogRevisionPositionHotspot.visual_page_id.in_(ids)).limit(1)))


def assign(db: Session, actor: User, page_id: int, data) -> dict:
    page, assembly, revision, catalog = load(db, page_id, mutate=True)
    check_version(page, data.expected_version)
    source, _, source_revision, _ = visual_sources._artifact(db, data.artifact_id)
    if source_revision.id != revision.id or any(not 1 <= number <= source.page_count for number in data.page_numbers):
        raise fail("catalog_visual_page_invalid", 422)
    if len(data.page_numbers) != len(set(data.page_numbers)) or len(data.roles) != len(set(data.roles)):
        raise fail("catalog_visual_page_invalid", 422)
    from .parts_extraction.ledger import invalidate_scope
    invalidate_scope(db, actor, assembly.id, page.id, "SOURCE_ASSIGNMENT_ADDED")
    alias = db.scalar(select(CatalogRevisionArtifact).where(
        CatalogRevisionArtifact.assembly_id == assembly.id, CatalogRevisionArtifact.sha256 == source.sha256))
    if alias is None:
        alias = CatalogRevisionArtifact(assembly_id=assembly.id, title=source.title, filename=source.filename,
            media_type=source.media_type, sha256=source.sha256, page_count=source.page_count,
            document_reference=source.document_reference, document_date=source.document_date,
            language=source.language, source_blob=source.source_blob or shared_blob(db, source.content, source.sha256),
            stored_content=b"", created_by_id=actor.id)
        db.add(alias)
        db.flush()
    order = db.scalar(select(func.max(CatalogRevisionVisualPage.sort_order)).where(
        CatalogRevisionVisualPage.reference_page_id == page.id))
    existing = {(item.page_number, item.role) for item in db.scalars(select(CatalogRevisionVisualPage).where(
        CatalogRevisionVisualPage.reference_page_id == page.id, CatalogRevisionVisualPage.artifact_id == alias.id))}
    try:
        for number in data.page_numbers:
            for role in data.roles:
                if (number, role) in existing:
                    continue
                order = (order if order is not None else -1) + 1
                db.add(CatalogRevisionVisualPage(reference_page_id=page.id, artifact_id=alias.id,
                    page_number=number, role=role, sort_order=order, created_by_id=actor.id))
        touch(page)
        db.flush()
        add_audit_log(db, actor, "catalog_reference_page", page.id, "REFERENCE_SOURCES_ASSIGNED",
            visual_sources._meta(catalog, revision, assembly, alias, page_numbers=data.page_numbers, roles=data.roles))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise fail("catalog_reference_page_stale") from exc
    return serialize(db, page)


def _same_ids(expected, received) -> bool:
    return len(received) == len(set(received)) and set(expected) == set(received)


def reorder_pages(db: Session, actor: User, assembly_id: int, data) -> list[dict]:
    assembly, revision, catalog = visual_sources._assembly(db, assembly_id, mutate=True)
    rows = list(db.scalars(select(CatalogRevisionReferencePage).where(
        CatalogRevisionReferencePage.assembly_id == assembly.id).with_for_update()))
    by_id = {row.id: row for row in rows}
    if not _same_ids(by_id, [item.id for item in data.pages]):
        raise fail("catalog_reference_page_stale")
    for item in data.pages:
        check_version(by_id[item.id], item.expected_version)
    for index, item in enumerate(data.pages):
        from .parts_extraction.ledger import invalidate_scope
        invalidate_scope(db, actor, assembly.id, item.id, "REFERENCE_PAGES_REORDERED")
        by_id[item.id].sort_order = index
        touch(by_id[item.id])
    add_audit_log(db, actor, "catalog_revision_assembly", assembly.id, "REFERENCE_PAGES_REORDERED",
        visual_sources._meta(catalog, revision, assembly, page_ids=[item.id for item in data.pages]))
    db.commit()
    return list_pages(db, assembly.id)


def reorder_references(db: Session, actor: User, revision_id: int, data) -> list[dict]:
    from ..models import CatalogRevisionAssembly
    revision, catalog = visual_sources._revision(db, revision_id, mutate=True)
    rows = list(db.scalars(select(CatalogRevisionAssembly).where(
        CatalogRevisionAssembly.revision_id == revision.id).order_by(
        CatalogRevisionAssembly.sort_order, CatalogRevisionAssembly.id).with_for_update()))
    by_id = {row.id: row for row in rows}
    if [row.id for row in rows] != data.expected_ids or not _same_ids(by_id, data.ordered_ids):
        raise fail("catalog_reference_page_stale")
    for index, identity in enumerate(data.ordered_ids):
        by_id[identity].sort_order = index
    add_audit_log(db, actor, "catalog_revision", revision.id, "REFERENCES_REORDERED",
        {"catalog_code": catalog.code, "revision_code": revision.revision_code, "ordered_ids": data.ordered_ids})
    db.commit()
    return visual_sources.list_assemblies(db, revision.id)


def reorder_sources(db: Session, actor: User, page_id: int, data) -> dict:
    page, assembly, revision, catalog = load(db, page_id, mutate=True)
    check_version(page, data.expected_version)
    rows = list(db.scalars(select(CatalogRevisionVisualPage).where(
        CatalogRevisionVisualPage.reference_page_id == page.id)))
    by_id = {row.id: row for row in rows}
    if not _same_ids(by_id, data.ordered_ids):
        raise fail("catalog_visual_page_invalid", 422)
    from .parts_extraction.ledger import invalidate_scope
    invalidate_scope(db, actor, assembly.id, page.id, "SOURCES_REORDERED")
    for index, identity in enumerate(data.ordered_ids):
        by_id[identity].sort_order = index
    touch(page)
    add_audit_log(db, actor, "catalog_reference_page", page.id, "REFERENCE_SOURCES_REORDERED",
        visual_sources._meta(catalog, revision, assembly, ordered_ids=data.ordered_ids))
    db.commit()
    return serialize(db, page)
