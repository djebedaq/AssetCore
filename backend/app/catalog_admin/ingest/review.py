"""Atomic human acceptance into proven Builder records and automatic page maps."""

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from ...audit import add_audit_log
from ...models import (
    CatalogIngestCandidate,
    CatalogRevisionArtifact,
    CatalogRevisionAssembly,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
    CatalogRevisionPositionHotspot,
    CatalogRevisionVisualPage,
    utcnow,
)
from .. import hotspots, parts, wizard, wizard_documents
from ..schemas import ClassifyDocumentPages, PartCreate
from ..service import fail
from . import candidates, runs
from .values import PLACEHOLDERS, POSITION, quantity


def group_candidate(db: Session, run_id: int, key: str) -> CatalogIngestCandidate:
    group = db.scalar(select(CatalogIngestCandidate).where(CatalogIngestCandidate.run_id == run_id,
        CatalogIngestCandidate.kind == "GROUP", CatalogIngestCandidate.source_key == key))
    if group is None:
        raise fail("catalog_ingest_group_required", 422)
    return group


def assembly_for(db: Session, run, payload: dict) -> CatalogRevisionAssembly:
    group = group_candidate(db, run.id, payload.get("group_key", ""))
    assembly = db.get(CatalogRevisionAssembly, group.target_id) if group.target_id else None
    if group.state != "ACCEPTED" or assembly is None or assembly.revision_id != run.revision_id:
        raise fail("catalog_ingest_group_required", 422)
    return assembly


def source_for(db: Session, run) -> CatalogRevisionArtifact:
    # The artifact ID is a historical snapshot, not a live foreign key. SQLite
    # may reuse a deleted integer PK; both SHA and revision remain authoritative.
    source = db.scalar(select(CatalogRevisionArtifact).join(CatalogRevisionAssembly).where(
        CatalogRevisionArtifact.id == run.artifact_id,
        CatalogRevisionAssembly.revision_id == run.revision_id,
        CatalogRevisionArtifact.sha256 == run.sha256))
    if source is None:
        source = db.scalar(select(CatalogRevisionArtifact).join(CatalogRevisionAssembly).where(
            CatalogRevisionAssembly.revision_id == run.revision_id, CatalogRevisionArtifact.sha256 == run.sha256))
    if source is None:
        raise fail("catalog_source_not_found", 404)
    return source


def page_for(db: Session, run, assembly_id: int, number: int, role: str) -> CatalogRevisionVisualPage:
    page = db.scalar(select(CatalogRevisionVisualPage).join(CatalogRevisionArtifact).where(
        CatalogRevisionArtifact.assembly_id == assembly_id, CatalogRevisionArtifact.sha256 == run.sha256,
        CatalogRevisionVisualPage.page_number == number, CatalogRevisionVisualPage.role == role))
    if page is None:
        raise fail("catalog_ingest_page_required", 422)
    return page


def accept_group(db: Session, actor, run, candidate) -> None:
    payload = candidate.payload
    if payload.get("merge_into_key"):
        other = group_candidate(db, run.id, payload["merge_into_key"])
        if other.id == candidate.id or other.state != "ACCEPTED" or not other.target_id:
            raise fail("catalog_ingest_group_required", 422)
        candidate.target_id = other.target_id
        return
    if payload.get("assembly_id"):
        group = db.get(CatalogRevisionAssembly, payload["assembly_id"])
        if group is None or group.revision_id != run.revision_id:
            raise fail("catalog_ingest_group_required", 422)
        candidate.target_id = group.id
        return
    name = (payload.get("name") or "").strip()
    if not name:
        raise fail("catalog_ingest_group_required", 422)
    # The unused initial upload group is infrastructure, not an invented assembly.
    source = source_for(db, run)
    group = db.get(CatalogRevisionAssembly, source.assembly_id)
    accepted_group = db.scalar(select(CatalogIngestCandidate.id).where(
        CatalogIngestCandidate.run_id == run.id, CatalogIngestCandidate.kind == "GROUP",
        CatalogIngestCandidate.state == "ACCEPTED", CatalogIngestCandidate.target_id == group.id))
    unused = not db.scalar(select(CatalogRevisionVisualPage.id).join(CatalogRevisionArtifact).where(
        CatalogRevisionArtifact.assembly_id == group.id).limit(1)) and not db.scalar(select(CatalogRevisionPart.id).where(
        CatalogRevisionPart.assembly_id == group.id).limit(1))
    if group.code == "INITIAL_GROUP" and unused and not accepted_group:
        group.name_bg, group.name_en, group.name_ru = name, "", ""
    else:
        group = CatalogRevisionAssembly(revision_id=run.revision_id,
            code=wizard.group_code(db, run.revision_id, name), name_bg=name, name_en="", name_ru="",
            description=None, created_by_id=actor.id)
        db.add(group)
        db.flush()
    candidate.target_id = group.id


def accept_page(db: Session, actor, run, candidate) -> None:
    role = candidate.payload["role"]
    if role == "AMBIGUOUS":
        raise fail("catalog_ingest_role_required", 422)
    if role == "OTHER":
        return
    assembly = assembly_for(db, run, candidate.payload)
    source = source_for(db, run)
    roles = ["EXPLODED_SCHEME", "SPARE_PARTS_LIST"] if role == "BOTH" else [role]
    wizard_documents.classify(db, actor, source.id, ClassifyDocumentPages(
        assembly_id=assembly.id, page_numbers=[candidate.page_number], roles=roles), commit=False)
    candidate.target_id = page_for(db, run, assembly.id, candidate.page_number, roles[0]).id


def accept_part(db: Session, actor, run, candidate) -> None:
    assembly = assembly_for(db, run, candidate.payload)
    values = {key: value for key, value in candidate.payload.items() if key in PartCreate.model_fields}
    if (not POSITION.fullmatch(values.get("position", ""))
            or str(values.get("part_number") or "").strip() in PLACEHOLDERS
            or str(values.get("description") or "").strip() in PLACEHOLDERS
            or quantity(str(values["quantity"]) if values.get("quantity") is not None else "") is None):
        raise fail("catalog_ingest_invalid", 422)
    try:
        clean = parts._clean(PartCreate(**values).model_dump())
    except ValidationError:
        raise fail("catalog_ingest_invalid", 422) from None
    page = page_for(db, run, assembly.id, candidate.page_number, "SPARE_PARTS_LIST")
    existing = db.scalar(select(CatalogRevisionPart).where(CatalogRevisionPart.assembly_id == assembly.id,
        CatalogRevisionPart.position == clean["position"], CatalogRevisionPart.part_number == clean["part_number"]))
    if existing is None:
        existing = CatalogRevisionPart(assembly_id=assembly.id, created_by_id=actor.id, **clean)
        db.add(existing)
        db.flush()
    elif any(getattr(existing, key) != clean.get(key) for key in ("description", "quantity")):
        # Never silently replace an existing human-edited variant.
        raise fail("catalog_part_duplicate")
    mapping = db.scalar(select(CatalogRevisionPartPageMap.id).where(
        CatalogRevisionPartPageMap.part_id == existing.id, CatalogRevisionPartPageMap.visual_page_id == page.id))
    if not mapping:
        db.add(CatalogRevisionPartPageMap(part_id=existing.id, visual_page_id=page.id, created_by_id=actor.id))
    candidate.target_id = existing.id


def accept_hotspot(db: Session, actor, run, candidate, selected: list[int] | None) -> None:
    assembly = assembly_for(db, run, candidate.payload)
    locations = candidate.payload["locations"]
    if selected is None:
        if candidate.payload["match"] != "EXACT":
            raise fail("catalog_ingest_location_required", 422)
        selected = [0]
    if len(set(selected)) != len(selected) or any(index < 0 or index >= len(locations) for index in selected):
        raise fail("catalog_ingest_location_required", 422)
    hotspots._position(db, assembly.id, candidate.payload["position"])
    accepted = []
    for index in selected:
        location = locations[index]
        page = page_for(db, run, assembly.id, location["page_number"], "EXPLODED_SCHEME")
        geometry = {key: location[key] for key in hotspots.GEOMETRY}
        hotspots._geometry(geometry)
        hotspot = CatalogRevisionPositionHotspot(visual_page_id=page.id,
            position=candidate.payload["position"], provenance="AUTO_INGEST_OCR" if location["method"] == "OCR" else "AUTO_INGEST_NATIVE",
            is_verified=False, created_by_id=actor.id, **geometry)
        db.add(hotspot)
        db.flush()
        accepted.append({"id": hotspot.id, "version": hotspot.version})
    candidate.target_id = accepted[0]["id"]
    candidate.payload = {**candidate.payload, "accepted_hotspots": accepted}


def verify_hotspots(db: Session, actor, run, candidate) -> None:
    if candidate.kind != "HOTSPOT" or candidate.state != "ACCEPTED":
        raise fail("catalog_ingest_location_required", 422)
    accepted = []
    assembly = assembly_for(db, run, candidate.payload)
    for linked in candidate.payload.get("accepted_hotspots", []):
        hotspot, _, _, owner, _, _ = hotspots._hotspot(db, linked["id"], mutate=True)
        if owner.id != assembly.id or hotspot.version != linked["version"]:
            raise fail("catalog_hotspot_stale")
        hotspot.is_verified = True
        hotspot.verified_by_id = actor.id
        hotspot.verified_at = utcnow()
        hotspot.version += 1
        accepted.append({"id": hotspot.id, "version": hotspot.version})
    candidate.payload = {**candidate.payload, "accepted_hotspots": accepted, "verified": True}


def apply(db: Session, actor, run, candidate, data) -> None:
    if candidate.version != data.expected_version:
        raise fail("catalog_ingest_stale")
    if data.action == "VERIFY":
        verify_hotspots(db, actor, run, candidate)
    elif candidate.state == "ACCEPTED":
        # Actual accepted draft records are edited in the existing editors.
        raise fail("catalog_ingest_use_editor")
    elif data.action == "EDIT":
        if not data.edit:
            raise fail("catalog_ingest_invalid", 422)
        changes = data.edit.model_dump(exclude_unset=True, mode="json")
        allowed = {"GROUP": {"name", "merge_into_key", "assembly_id"},
                   "PAGE": {"role", "group_key"}, "PART": {"part", "group_key"}, "HOTSPOT": set()}
        if set(changes) - allowed[candidate.kind] or any(value is None and key not in {"merge_into_key", "assembly_id"} for key, value in changes.items()):
            raise fail("catalog_ingest_invalid", 422)
        if "group_key" in changes:
            group_candidate(db, run.id, changes["group_key"])
            if candidate.kind == "PAGE":
                related = db.scalars(select(CatalogIngestCandidate).where(
                    CatalogIngestCandidate.run_id == run.id, CatalogIngestCandidate.kind == "PART",
                    CatalogIngestCandidate.page_number == candidate.page_number)).all()
                if any(row.state == "ACCEPTED" for row in related):
                    raise fail("catalog_ingest_use_editor")
                for row in related:
                    row.payload = {**row.payload, "group_key": changes["group_key"]}
                    row.version += 1
                    row.reviewed_by_id = actor.id
                    row.reviewed_at = utcnow()
        if changes.get("merge_into_key"):
            group_candidate(db, run.id, changes["merge_into_key"])
        if "part" in changes:
            changes.update(changes.pop("part"))
        candidate.payload = {**candidate.payload, **changes}
        candidate.state = "NEEDS_REVIEW"
    elif data.action == "ACCEPT":
        if candidate.state == "REJECTED":
            raise fail("catalog_ingest_restore_required")
        if candidate.kind == "GROUP":
            accept_group(db, actor, run, candidate)
        elif candidate.kind == "PAGE":
            accept_page(db, actor, run, candidate)
        elif candidate.kind == "PART":
            accept_part(db, actor, run, candidate)
        else:
            accept_hotspot(db, actor, run, candidate, data.locations)
        candidate.state = "ACCEPTED"
    elif data.action == "REJECT":
        candidate.state = "REJECTED"
    elif data.action == "RESTORE":
        candidate.state = "NEEDS_REVIEW"
    candidate.version += 1
    candidate.reviewed_by_id = actor.id
    candidate.reviewed_at = utcnow()
    db.flush()


def review_one(db: Session, actor, run_id: int, candidate_id: int, data) -> dict:
    run = runs.load_run(db, run_id, mutate=True)
    if run.status != "COMPLETED":
        raise fail("catalog_ingest_not_completed")
    candidate = db.scalar(select(CatalogIngestCandidate).where(CatalogIngestCandidate.id == candidate_id,
        CatalogIngestCandidate.run_id == run.id).with_for_update().execution_options(populate_existing=True))
    if candidate is None:
        raise fail("catalog_ingest_not_found", 404)
    try:
        apply(db, actor, run, candidate, data)
    except (StaleDataError, IntegrityError):
        db.rollback()
        raise fail("catalog_ingest_stale") from None
    add_audit_log(db, actor, "catalog_ingest_candidate", candidate.id, f"CATALOG_CANDIDATE_{data.action}",
                  {"kind": candidate.kind, "sha256": run.sha256, "page_number": candidate.page_number,
                   "version": candidate.version, "target_id": candidate.target_id})
    db.commit()
    return candidates.candidate_dict(candidate, run)


def bulk(db: Session, actor, run_id: int, data) -> dict:
    from .schemas import CandidateReview

    run = runs.load_run(db, run_id, mutate=True)
    if run.status != "COMPLETED" or len({item.id for item in data.items}) != len(data.items):
        raise fail("catalog_ingest_invalid", 422)
    requested = {item.id: item.expected_version for item in data.items}
    rows = db.scalars(select(CatalogIngestCandidate).where(CatalogIngestCandidate.run_id == run.id,
        CatalogIngestCandidate.id.in_(requested)).order_by(CatalogIngestCandidate.id)
        .with_for_update().execution_options(populate_existing=True)).all()
    if len(rows) != len(requested):
        raise fail("catalog_ingest_not_found", 404)
    priority = {"GROUP": 0, "PAGE": 1, "PART": 2, "HOTSPOT": 3}
    try:
        for row in sorted(rows, key=lambda row: (priority[row.kind], bool(row.payload.get("merge_into_key")), row.id)):
            apply(db, actor, run, row, CandidateReview(action=data.action, expected_version=requested[row.id]))
    except (StaleDataError, IntegrityError):
        db.rollback()
        raise fail("catalog_ingest_stale") from None
    add_audit_log(db, actor, "catalog_ingest_run", run.id, f"CATALOG_CANDIDATES_BULK_{data.action}",
                  {"candidate_ids": sorted(requested), "count": len(rows)})
    db.commit()
    return {"count": len(rows)}
