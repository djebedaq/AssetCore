"""Audited, exact-page supplemental compatibility; never copies published data."""

from collections import defaultdict

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..assets.capabilities import supports
from ..audit import add_audit_log
from ..models import (
    CatalogDefinition,
    CatalogDiagram,
    CatalogReferenceAssociation,
    CatalogReferencePart,
    CatalogRevision,
    CatalogVisualPartMap,
    CatalogVisualSource,
    Machine,
    PartCatalog,
    User,
    utcnow,
)
from ..workflow import business_conflict


class ReferenceCreate(BaseModel):
    machine_ids: list[int] = Field(min_length=1, max_length=100)
    scheme_id: int = Field(gt=0)
    parts_list_id: int = Field(gt=0)
    part_ids: list[int] = Field(min_length=1, max_length=500)
    source_revision: str = Field(min_length=1, max_length=255)
    compatibility_confirmed: bool
    reason: str = Field(min_length=3, max_length=4000)


class ReferenceRevoke(BaseModel):
    reason: str = Field(min_length=3, max_length=4000)


def available(db, row):
    if row.builder_revision_id is None:
        from .sources import CATALOG_VERSION
        return row.source_revision == CATALOG_VERSION if isinstance(row, CatalogReferenceAssociation) else row.catalog_revision == CATALOG_VERSION
    revision = db.get(CatalogRevision, row.builder_revision_id)
    catalog = db.get(CatalogDefinition, revision.catalog_id) if revision else None
    return bool(revision and revision.status == "PUBLISHED" and catalog and catalog.is_active)


def verify_source(db, source):
    from . import service
    if not available(db, source):
        raise business_conflict("catalog_reference_source_unavailable", "Източникът не е публикуван.")
    if source.builder_revision_id:
        service._builder_integrity(db, source.builder_revision_id)
    else:
        service.ensure_integrity(source.source_id)


def page_dict(page):
    return {"id": page.id, "page_number": page.page_number, "role": page.role,
            "sha256": page.source_sha256, "technical_document_id": page.technical_document_id,
            "preview_endpoint": f"/technical-library/{page.technical_document_id}/pages/{page.page_number}/preview?scale=1"}


def sources(db):
    groups = defaultdict(list)
    for page in db.scalars(select(CatalogVisualSource).order_by(CatalogVisualSource.id)):
        if available(db, page):
            groups[(page.source_id, page.catalog_revision)].append(page)
    return [{"source_id": key[0], "revision": key[1],
             "title": pages[0].technical_document.title,
             "pages": [page_dict(page) for page in pages]}
            for key, pages in groups.items()
            if any(page.role == "EXPLODED_SCHEME" for page in pages)
            and any(page.role == "SPARE_PARTS_LIST" for page in pages)]


def list_parts(db, list_id):
    from .service import serialize_part
    source = db.get(CatalogVisualSource, list_id)
    if source is None or source.role != "SPARE_PARTS_LIST":
        raise business_conflict("catalog_reference_invalid_list", "Изберете точен списък с части.")
    verify_source(db, source)
    return [serialize_part(part) for part in db.scalars(select(PartCatalog)
            .join(CatalogVisualPartMap, CatalogVisualPartMap.part_id == PartCatalog.id)
            .where(CatalogVisualPartMap.visual_source_id == list_id,
                   PartCatalog.is_active.is_(True), PartCatalog.is_verified.is_(True),
                   func.trim(PartCatalog.part_number) != "")
            .order_by(PartCatalog.source_row_index, PartCatalog.id))]


def association_dict(db, row):
    actor = db.get(User, row.confirmed_by_id)
    return {"id": row.id, "machine_id": row.machine_id, "source_id": row.source_id,
            "revision": row.source_revision, "confirmed_by": actor.full_name if actor else None,
            "confirmed_at": row.confirmed_at, "reason": row.reason,
            "available": available(db, row) and row.revoked_at is None,
            "revoked_at": row.revoked_at, "evidence": row.evidence,
            "part_ids": list(db.scalars(select(CatalogReferencePart.part_id)
                .where(CatalogReferencePart.association_id == row.id)))}


def associations(db, machine_id, source_id=None):
    query = select(CatalogReferenceAssociation).where(
        CatalogReferenceAssociation.machine_id == machine_id,
        CatalogReferenceAssociation.revoked_at.is_(None))
    if source_id:
        query = query.where(CatalogReferenceAssociation.source_id == source_id)
    return list(db.scalars(query.order_by(CatalogReferenceAssociation.id)))


def active_source(db, machine_id, source_id):
    rows = [row for row in associations(db, machine_id, source_id) if available(db, row)]
    if not rows:
        return None
    source = db.get(CatalogVisualSource, rows[0].scheme_id)
    verify_source(db, source)
    part_ids = set(db.scalars(select(CatalogReferencePart.part_id).where(
        CatalogReferencePart.association_id.in_([row.id for row in rows]))))
    return {"rows": rows, "part_ids": part_ids, "builder_revision_id": source.builder_revision_id,
            "scheme_ids": {row.scheme_id for row in rows}}


def permits_part(db, machine, part):
    if machine is None or not supports(machine, "HAS_PARTS_CATALOG"):
        return False
    if part.builder_revision_id:
        revision = db.get(CatalogRevision, part.builder_revision_id)
        if revision:
            db.scalar(select(CatalogDefinition).where(CatalogDefinition.id == revision.catalog_id)
                      .with_for_update(read=True).execution_options(populate_existing=True))
            db.refresh(revision)
    shared = active_source(db, machine.id, part.source_id)
    return bool(shared and part.id in shared["part_ids"] and part.is_verified and part.is_active
                and part.builder_revision_id == shared["builder_revision_id"])


def create(db, actor, data):
    if not data.compatibility_confirmed or len(data.reason.strip()) < 3:
        raise business_conflict("catalog_reference_confirmation_required", "Потвърдете техническата съвместимост.")
    ids = sorted(set(data.machine_ids))
    # Same machine-first ordering as requests and publication. A revoke cannot
    # race a request through the compatibility check on PostgreSQL.
    machines = list(db.scalars(select(Machine).where(Machine.id.in_(ids)).order_by(Machine.id)
                              .with_for_update().execution_options(populate_existing=True)))
    if len(machines) != len(ids) or any(not supports(m, "HAS_PARTS_CATALOG") or not m.is_active for m in machines):
        raise business_conflict("catalog_reference_invalid_machine", "Невалидна целева машина.")
    scheme, parts_list = (db.get(CatalogVisualSource, value) for value in (data.scheme_id, data.parts_list_id))
    if (scheme is None or parts_list is None or scheme.role != "EXPLODED_SCHEME"
            or parts_list.role != "SPARE_PARTS_LIST" or scheme.source_id != parts_list.source_id
            or scheme.catalog_revision != parts_list.catalog_revision
            or scheme.catalog_revision != data.source_revision):
        raise business_conflict("catalog_reference_page_mismatch", "Страниците не са от една логическа референция и ревизия.")
    if scheme.builder_revision_id:
        revision = db.get(CatalogRevision, scheme.builder_revision_id)
        db.scalar(select(CatalogDefinition).where(CatalogDefinition.id == revision.catalog_id)
                  .with_for_update(read=True).execution_options(populate_existing=True))
        db.refresh(revision)
    verify_source(db, scheme)
    verify_source(db, parts_list)
    available_parts = {part["id"]: part for part in list_parts(db, parts_list.id)}
    selected = sorted(set(data.part_ids))
    if not set(selected).issubset(available_parts):
        raise business_conflict("catalog_reference_part_mismatch", "Избран вариант не принадлежи към проверения списък.")
    output = []
    for machine in machines:
        if any(row.scheme_id == scheme.id and row.parts_list_id == parts_list.id
               for row in associations(db, machine.id)):
            raise business_conflict("catalog_reference_exists", "Референцията вече е свързана.")
        evidence = {"scheme": page_dict(scheme), "parts_list": page_dict(parts_list),
                    "parts": [{key: available_parts[part_id].get(key) for key in
                               ("id", "source_record_key", "part_number", "position", "valid_for_raw",
                                "replaced_by_part_number", "alternative_part_number", "source_document_sha256")}
                              for part_id in selected]}
        row = CatalogReferenceAssociation(machine_id=machine.id, source_id=scheme.source_id,
            source_revision=scheme.catalog_revision, builder_revision_id=scheme.builder_revision_id,
            scheme_id=scheme.id, parts_list_id=parts_list.id, confirmed_by_id=actor.id,
            reason=data.reason.strip(), evidence=evidence)
        db.add(row)
        db.flush()
        db.add_all([CatalogReferencePart(association_id=row.id, part_id=part_id) for part_id in selected])
        db.flush()
        add_audit_log(db, actor, "catalog_reference_association", row.id, "CATALOG_REFERENCE_CONFIRMED",
                      {"machine_id": machine.id, "revision": row.source_revision,
                       "source_id": row.source_id, "reason": row.reason, "evidence": evidence})
        output.append(association_dict(db, row))
    db.commit()
    return output


def revoke(db, actor, association_id, reason):
    row = db.get(CatalogReferenceAssociation, association_id)
    if row is None or len(reason.strip()) < 3:
        raise business_conflict("catalog_reference_not_found", "Невалидна референция или основание.")
    db.scalar(select(Machine).where(Machine.id == row.machine_id).with_for_update())
    db.refresh(row)
    if row.revoked_at is None:
        row.revoked_at, row.revoked_by_id, row.revoke_reason = utcnow(), actor.id, reason.strip()
        add_audit_log(db, actor, "catalog_reference_association", row.id, "CATALOG_REFERENCE_REVOKED",
                      {"machine_id": row.machine_id, "reason": reason.strip()})
    db.commit()
    return association_dict(db, row)


def supplemental_assemblies(db, machine_id):
    from .service import serialize_diagram
    result = []
    for source_id in dict.fromkeys(row.source_id for row in associations(db, machine_id)):
        shared = active_source(db, machine_id, source_id)
        if not shared:
            continue
        pages = list(db.scalars(select(CatalogVisualSource).where(CatalogVisualSource.id.in_(shared["scheme_ids"]))))
        diagrams = list(db.scalars(select(CatalogDiagram).where(CatalogDiagram.source_id == source_id)))
        diagrams = [d for d in diagrams if any(d.technical_document_id == p.technical_document_id
                                              and d.page_number == p.page_number for p in pages)]
        result.append({"source_id": source_id, "family": "SHARED_REFERENCE", "assembly": source_id,
            "title": pages[0].technical_document.title, "document_reference": shared["rows"][0].source_revision,
            "part_count": len(shared["part_ids"]), "diagram_count": len(diagrams),
            "verified_hotspot_count": 0, "diagrams": [serialize_diagram(d) for d in diagrams],
            "is_supplemental": True})
    return result
