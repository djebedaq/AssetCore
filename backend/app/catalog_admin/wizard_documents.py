"""A single original PDF presented across existing assembly-owned artifacts."""

from __future__ import annotations

import re

import fitz
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..models import (
    CatalogRevisionArtifact,
    CatalogRevisionAssembly,
    CatalogRevisionPartPageMap,
    CatalogRevisionPositionHotspot,
    CatalogRevisionVisualPage,
    User,
)
from . import service, visual_sources
from .schemas import ClassifyDocumentPages


def documents(db: Session, revision_id: int) -> list[dict]:
    visual_sources._revision(db, revision_id)
    assemblies = select(CatalogRevisionAssembly.id).where(CatalogRevisionAssembly.revision_id == revision_id)
    artifacts = db.scalars(select(CatalogRevisionArtifact).where(
        CatalogRevisionArtifact.assembly_id.in_(assemblies)).order_by(CatalogRevisionArtifact.id)).all()
    pages = db.scalars(select(CatalogRevisionVisualPage).where(
        CatalogRevisionVisualPage.artifact_id.in_([item.id for item in artifacts]))).all()
    grouped = {}
    by_id = {item.id: item for item in artifacts}
    for item in artifacts:
        grouped.setdefault(item.sha256, {**visual_sources._artifact_dict(item), "artifact_ids": [], "assignments": []})
        grouped[item.sha256]["artifact_ids"].append(item.id)
    for page in pages:
        artifact = by_id[page.artifact_id]
        grouped[artifact.sha256]["assignments"].append({
            **visual_sources._page_dict(page), "assembly_id": artifact.assembly_id,
        })
    return list(grouped.values())


def suggestions(db: Session, artifact_id: int) -> dict:
    artifact, _, _, _ = visual_sources._artifact(db, artifact_id)
    output, headings = [], []
    with fitz.open(stream=artifact.content, filetype="pdf") as pdf:
        for number, page in enumerate(pdf, 1):
            text = page.get_text()[:16000]
            normalized = text.casefold()
            role = None
            # Conservative text-only hints; never create pages, groups or parts.
            if (re.search(r"part\s*(no|number|№)|номер.*част|номер.*детал", normalized)
                    and re.search(r"\bqty\b|quantity|количество|количество", normalized)):
                role = "SPARE_PARTS_LIST"
            elif re.search(r"exploded\s+(view|scheme)|разглобена\s+схема|взрыв.?схема", normalized):
                role = "EXPLODED_SCHEME"
            candidates = [line.strip() for line in text.splitlines() if 3 <= len(line.strip()) <= 100
                          and re.search(r"\b(assembly|system)\b|възел|система|узел", line, re.I)]
            heading = candidates[0] if candidates else None
            if heading and heading not in headings and len(headings) < 50:
                headings.append(heading)
            if role or heading:
                output.append({"page_number": number, "suggested_role": role, "suggested_group_name": heading})
    return {"pages": output, "group_names": headings, "requires_confirmation": True}


def classify(db: Session, actor: User, artifact_id: int, data: ClassifyDocumentPages) -> list[dict]:
    source, _, revision, catalog = visual_sources._artifact(db, artifact_id, mutate=True)
    owned_group = db.scalar(select(CatalogRevisionAssembly.id).where(
        CatalogRevisionAssembly.id == data.assembly_id, CatalogRevisionAssembly.revision_id == revision.id))
    if owned_group is None:
        raise service.fail("catalog_visual_page_invalid", 422)
    target, target_revision, _ = visual_sources._assembly(db, data.assembly_id, mutate=True)
    if target_revision.id != revision.id:
        raise service.fail("catalog_visual_page_invalid", 422)
    numbers = data.page_numbers
    if (len(set(numbers)) != len(numbers) or any(not 1 <= number <= source.page_count for number in numbers)
            or len(set(data.roles)) != len(data.roles) or set(data.roles) - visual_sources.ROLES):
        raise service.fail("catalog_visual_page_invalid", 422)
    assembly_ids = select(CatalogRevisionAssembly.id).where(CatalogRevisionAssembly.revision_id == revision.id)
    aliases = db.scalars(select(CatalogRevisionArtifact).where(
        CatalogRevisionArtifact.assembly_id.in_(assembly_ids), CatalogRevisionArtifact.sha256 == source.sha256)).all()
    ids = [item.id for item in aliases]
    alias_by_id = {item.id: item for item in aliases}
    current = db.scalars(select(CatalogRevisionVisualPage).where(
        CatalogRevisionVisualPage.artifact_id.in_(ids), CatalogRevisionVisualPage.page_number.in_(numbers))).all()
    removed = [page for page in current if alias_by_id[page.artifact_id].assembly_id != target.id
               or page.role not in data.roles]
    removed_ids = [page.id for page in removed]
    from .repair_kits import source_page_reference_count
    if (removed_ids and (source_page_reference_count(db, removed_ids)
            or db.scalar(select(CatalogRevisionPartPageMap.id).where(
                CatalogRevisionPartPageMap.visual_page_id.in_(removed_ids)).limit(1))
            or db.scalar(select(CatalogRevisionPositionHotspot.id).where(
                CatalogRevisionPositionHotspot.visual_page_id.in_(removed_ids)).limit(1)))):
        raise service.fail("catalog_wizard_page_in_use")
    target_artifact = next((item for item in aliases if item.assembly_id == target.id), None)
    try:
        if data.roles and target_artifact is None:
            # Keep the established assembly ownership contract and original byte/hash provenance.
            values = {key: getattr(source, key) for key in (
                "title", "filename", "media_type", "content", "sha256", "page_count",
                "document_reference", "document_date", "language")}
            target_artifact = CatalogRevisionArtifact(assembly_id=target.id, created_by_id=actor.id, **values)
            db.add(target_artifact)
            db.flush()
            add_audit_log(db, actor, "catalog_revision_artifact", target_artifact.id, "CATALOG_SOURCE_LINKED",
                          visual_sources._meta(catalog, revision, target, target_artifact,
                                               original_artifact_id=source.id))
        if removed_ids:
            db.execute(delete(CatalogRevisionVisualPage).where(CatalogRevisionVisualPage.id.in_(removed_ids)))
        existing = {(page.page_number, page.role) for page in current
                    if page.id not in removed_ids and alias_by_id[page.artifact_id].assembly_id == target.id}
        for number in numbers:
            for role in data.roles:
                if (number, role) not in existing:
                    db.add(CatalogRevisionVisualPage(artifact_id=target_artifact.id,
                           page_number=number, role=role, created_by_id=actor.id))
        add_audit_log(db, actor, "catalog_revision_artifact", source.id, "DOCUMENT_PAGES_CLASSIFIED",
                      visual_sources._meta(catalog, revision, target, source,
                          page_numbers=numbers, roles=data.roles, removed_visual_page_ids=removed_ids))
        db.flush()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise service.fail("catalog_visual_page_duplicate") from exc
    return documents(db, revision.id)
