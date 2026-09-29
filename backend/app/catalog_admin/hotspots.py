"""Explicit, position-centric exploded-scheme staging for draft revisions."""

import math

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..models import (
    CatalogRevisionArtifact,
    CatalogRevisionPart,
    CatalogRevisionPositionHotspot,
    CatalogRevisionVisualPage,
    User,
    utcnow,
)
from .schemas import HotspotCreate, HotspotUpdate
from .service import fail
from .visual_sources import _artifact, _assembly, _meta

GEOMETRY = ("x", "y", "width", "height")
MIN_SIZE = 0.002


def _page(db: Session, page_id: int, *, mutate: bool = False):
    page = db.get(CatalogRevisionVisualPage, page_id)
    if page is None:
        raise fail("catalog_exploded_page_not_found", 404)
    artifact, assembly, revision, catalog = _artifact(db, page.artifact_id, mutate=mutate)
    if mutate:
        page = db.scalar(select(CatalogRevisionVisualPage).where(CatalogRevisionVisualPage.id == page_id)
                         .execution_options(populate_existing=True))
    if page is None or page.artifact_id != artifact.id or page.role != "EXPLODED_SCHEME":
        raise fail("catalog_exploded_page_not_found", 404)
    return page, artifact, assembly, revision, catalog


def _hotspot(db: Session, hotspot_id: int, *, mutate: bool = False):
    hotspot = db.get(CatalogRevisionPositionHotspot, hotspot_id)
    if hotspot is None:
        raise fail("catalog_hotspot_not_found", 404)
    page, artifact, assembly, revision, catalog = _page(db, hotspot.visual_page_id, mutate=mutate)
    if mutate:
        hotspot = db.scalar(select(CatalogRevisionPositionHotspot)
                            .where(CatalogRevisionPositionHotspot.id == hotspot_id)
                            .with_for_update().execution_options(populate_existing=True))
    if hotspot is None or hotspot.visual_page_id != page.id:
        raise fail("catalog_hotspot_not_found", 404)
    return hotspot, page, artifact, assembly, revision, catalog


def _check_version(item: CatalogRevisionPositionHotspot, expected: int) -> None:
    if item.version != expected:
        raise fail("catalog_hotspot_stale")


def _geometry(values: dict) -> None:
    if (any(not isinstance(values[key], (int, float)) or not math.isfinite(values[key]) for key in GEOMETRY)
            or not 0 <= values["x"] <= 1 or not 0 <= values["y"] <= 1
            or values["width"] < MIN_SIZE or values["height"] < MIN_SIZE
            or values["x"] + values["width"] > 1
            or values["y"] + values["height"] > 1):
        raise fail("catalog_hotspot_geometry_invalid", 422)


def _position(db: Session, assembly_id: int, position: str) -> None:
    if (not position or not position.strip() or position != position.strip()
            or db.scalar(select(CatalogRevisionPart.id).where(
                CatalogRevisionPart.assembly_id == assembly_id,
                CatalogRevisionPart.position == position).limit(1)) is None):
        raise fail("catalog_hotspot_position_invalid", 422)


def _dict(item: CatalogRevisionPositionHotspot) -> dict:
    return {key: getattr(item, key) for key in (
        "id", "visual_page_id", "position", *GEOMETRY, "provenance", "is_verified",
        "verified_by_id", "verified_at", "version", "created_at", "updated_at")}


def exploded_pages(db: Session, assembly_id: int) -> list[dict]:
    _assembly(db, assembly_id)
    rows = db.execute(select(CatalogRevisionVisualPage, CatalogRevisionArtifact)
                      .join(CatalogRevisionArtifact, CatalogRevisionVisualPage.artifact_id == CatalogRevisionArtifact.id)
                      .where(CatalogRevisionArtifact.assembly_id == assembly_id,
                             CatalogRevisionVisualPage.role == "EXPLODED_SCHEME")
                      .order_by(CatalogRevisionArtifact.id, CatalogRevisionVisualPage.page_number)).all()
    output = []
    for page, artifact in rows:
        count, verified = db.execute(select(func.count(CatalogRevisionPositionHotspot.id),
                                            func.count(CatalogRevisionPositionHotspot.id).filter(
                                                CatalogRevisionPositionHotspot.is_verified.is_(True)))
                                     .where(CatalogRevisionPositionHotspot.visual_page_id == page.id)).one()
        output.append({"visual_page_id": page.id, "artifact_id": artifact.id,
                       "artifact_title": artifact.title, "filename": artifact.filename,
                       "sha256": artifact.sha256, "page_number": page.page_number,
                       "hotspot_count": count, "verified_hotspot_count": verified})
    return output


def list_hotspots(db: Session, page_id: int) -> list[dict]:
    _page(db, page_id)
    return [_dict(item) for item in db.scalars(select(CatalogRevisionPositionHotspot)
            .where(CatalogRevisionPositionHotspot.visual_page_id == page_id)
            .order_by(CatalogRevisionPositionHotspot.id)).all()]


def coverage(db: Session, assembly_id: int) -> list[dict]:
    _assembly(db, assembly_id)
    parts = db.execute(select(CatalogRevisionPart.position, CatalogRevisionPart.part_number)
                       .where(CatalogRevisionPart.assembly_id == assembly_id)
                       .order_by(CatalogRevisionPart.position, CatalogRevisionPart.id)).all()
    page_ids = select(CatalogRevisionVisualPage.id).join(
        CatalogRevisionArtifact, CatalogRevisionVisualPage.artifact_id == CatalogRevisionArtifact.id).where(
            CatalogRevisionArtifact.assembly_id == assembly_id,
            CatalogRevisionVisualPage.role == "EXPLODED_SCHEME")
    hotspots = db.execute(select(CatalogRevisionPositionHotspot.position, CatalogRevisionPositionHotspot.is_verified)
                          .where(CatalogRevisionPositionHotspot.visual_page_id.in_(page_ids))).all()
    result: dict[str, dict] = {}
    for position, part_number in parts:
        row = result.setdefault(position, {"position": position, "part_count": 0, "part_numbers": [],
                                            "hotspot_count": 0, "verified_hotspot_count": 0})
        row["part_count"] += 1
        row["part_numbers"].append(part_number)
    for position, verified in hotspots:
        if position in result:
            result[position]["hotspot_count"] += 1
            result[position]["verified_hotspot_count"] += int(verified)
    for row in result.values():
        row["state"] = ("NO_HOTSPOT" if not row["hotspot_count"] else
                        "VERIFIED" if row["verified_hotspot_count"] == row["hotspot_count"] else "UNVERIFIED")
    return list(result.values())


def create_hotspot(db: Session, actor: User, page_id: int, data: HotspotCreate) -> dict:
    page, artifact, assembly, revision, catalog = _page(db, page_id, mutate=True)
    values = data.model_dump()
    _position(db, assembly.id, values["position"])
    _geometry(values)
    item = CatalogRevisionPositionHotspot(visual_page_id=page.id, provenance="MANUAL_BUILDER",
                                          is_verified=False, created_by_id=actor.id, **values)
    db.add(item)
    db.flush()
    add_audit_log(db, actor, "catalog_revision_position_hotspot", item.id, "BUILDER_HOTSPOT_CREATED",
                  _meta(catalog, revision, assembly, artifact, visual_page_id=page.id,
                        page_number=page.page_number, position=item.position,
                        geometry={key: getattr(item, key) for key in GEOMETRY}, is_verified=False))
    db.commit()
    return _dict(item)


def update_hotspot(db: Session, actor: User, hotspot_id: int, data: HotspotUpdate) -> dict:
    item, page, artifact, assembly, revision, catalog = _hotspot(db, hotspot_id, mutate=True)
    _check_version(item, data.expected_version)
    changes = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    if any(value is None for value in changes.values()):
        raise fail("catalog_hotspot_geometry_invalid", 422)
    values = {"position": item.position, **{key: getattr(item, key) for key in GEOMETRY}, **changes}
    _position(db, assembly.id, values["position"])
    _geometry(values)
    before = {key: getattr(item, key) for key in changes}
    changed = any(before[key] != value for key, value in changes.items())
    if changed:
        was_verified = item.is_verified
        for key, value in changes.items():
            setattr(item, key, value)
        item.is_verified = False
        item.verified_by_id = None
        item.verified_at = None
        item.version += 1
        item.updated_at = utcnow()
        add_audit_log(db, actor, "catalog_revision_position_hotspot", item.id, "BUILDER_HOTSPOT_UPDATED",
                      _meta(catalog, revision, assembly, artifact, visual_page_id=page.id,
                            page_number=page.page_number, position=item.position,
                            before=before, after={key: getattr(item, key) for key in changes},
                            geometry={key: getattr(item, key) for key in GEOMETRY},
                            verified_before=was_verified, verified_after=False))
        db.commit()
    return _dict(item)


def set_verified(db: Session, actor: User, hotspot_id: int, expected_version: int, verified: bool) -> dict:
    item, page, artifact, assembly, revision, catalog = _hotspot(db, hotspot_id, mutate=True)
    _check_version(item, expected_version)
    _position(db, assembly.id, item.position)
    _geometry({key: getattr(item, key) for key in GEOMETRY})
    before = item.is_verified
    if before != verified:
        item.is_verified = verified
        item.verified_by_id = actor.id if verified else None
        item.verified_at = utcnow() if verified else None
        item.version += 1
        item.updated_at = utcnow()
        add_audit_log(db, actor, "catalog_revision_position_hotspot", item.id,
                      "BUILDER_HOTSPOT_VERIFIED" if verified else "BUILDER_HOTSPOT_UNVERIFIED",
                      _meta(catalog, revision, assembly, artifact, visual_page_id=page.id,
                            page_number=page.page_number, position=item.position,
                            geometry={key: getattr(item, key) for key in GEOMETRY},
                            verified_before=before, verified_after=verified))
        db.commit()
    return _dict(item)


def delete_hotspot(db: Session, actor: User, hotspot_id: int, expected_version: int) -> None:
    item, page, artifact, assembly, revision, catalog = _hotspot(db, hotspot_id, mutate=True)
    _check_version(item, expected_version)
    add_audit_log(db, actor, "catalog_revision_position_hotspot", item.id, "BUILDER_HOTSPOT_DELETED",
                  _meta(catalog, revision, assembly, artifact, visual_page_id=page.id,
                        page_number=page.page_number, position=item.position,
                        geometry={key: getattr(item, key) for key in GEOMETRY},
                        verified_before=item.is_verified, verified_after=False))
    db.delete(item)
    db.commit()


def remove_page_hotspots(db: Session, actor: User, page_ids, catalog, revision, assembly) -> dict:
    """Delete descendants inside an existing locked page/artifact transaction."""
    rows = db.scalars(select(CatalogRevisionPositionHotspot).where(
        CatalogRevisionPositionHotspot.visual_page_id.in_(page_ids))).all()
    ids = [row.id for row in rows]
    if ids:
        add_audit_log(db, actor, "catalog_revision_assembly", assembly.id, "BUILDER_HOTSPOT_DELETED",
                      _meta(catalog, revision, assembly, hotspot_ids=ids, hotspot_count=len(ids)))
        db.execute(delete(CatalogRevisionPositionHotspot).where(CatalogRevisionPositionHotspot.id.in_(ids)))
    return {"hotspot_ids": ids, "hotspot_count": len(ids)}
