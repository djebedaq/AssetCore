"""Durable source review. All writes share the catalog publication lock.

Selection snapshots and completed attempts are retained. Current approval is a
content fingerprint, never an inference from OCR success or a nonempty catalog.
"""
import hashlib
import json
from collections import Counter
from datetime import timedelta

from sqlalchemy import select

from ...audit import add_audit_log
from ...models import (
    CatalogExtractionAttempt as Attempt,
)
from ...models import (
    CatalogExtractionCandidate as Candidate,
)
from ...models import (
    CatalogExtractionSession as ExtractionSession,
)
from ...models import (
    CatalogExtractionSource as Source,
)
from ...models import (
    CatalogRevisionArtifact,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
    CatalogRevisionReferencePage,
    CatalogRevisionVisualPage,
    utcnow,
)
from ...models import (
    CatalogSourceReviewDecision as Decision,
)
from ...settings import settings
from .. import visual_sources
from ..schemas import PartCreate
from ..service import fail


def hashed(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def selection(db, assembly_id, reference_page_id):
    rows = db.execute(select(CatalogRevisionVisualPage, CatalogRevisionArtifact).join(
        CatalogRevisionArtifact, CatalogRevisionVisualPage.artifact_id == CatalogRevisionArtifact.id).where(
        CatalogRevisionArtifact.assembly_id == assembly_id,
        CatalogRevisionVisualPage.reference_page_id == reference_page_id).order_by(CatalogRevisionVisualPage.id)).all()
    return [{"visual_page_id": p.id, "artifact_id": a.id, "sha256": a.sha256,
             "page_number": p.page_number, "filename": a.filename, "role": p.role,
             "sort_order": p.sort_order, "title": a.title, "page_count": a.page_count,
             "document_reference": a.document_reference, "document_date": str(a.document_date),
             "language": a.language} for p, a in rows]


def session(db, actor, assembly, revision, reference_page_id, *, create=False):
    chosen = selection(db, assembly.id, reference_page_id)
    fingerprint = hashed(chosen)
    scope = f"P{reference_page_id}" if reference_page_id is not None else f"A{assembly.id}"
    item = db.scalar(select(ExtractionSession).where(ExtractionSession.revision_id == revision.id,
        ExtractionSession.scope_key == scope, ExtractionSession.selection_digest == fingerprint))
    if item is None and create:
        item = ExtractionSession(revision_id=revision.id, assembly_id=assembly.id,
            reference_page_id=reference_page_id, scope_key=scope, selection_digest=fingerprint,
            selection=chosen, created_by_id=actor.id)
        db.add(item)
        db.flush()
        for source in chosen:
            if source["role"] == "SPARE_PARTS_LIST":
                from ..source_storage import shared_blob
                artifact = db.get(CatalogRevisionArtifact, source["artifact_id"])
                raw = artifact.content
                if hashlib.sha256(raw).hexdigest() != source["sha256"]:
                    raise fail("catalog_source_integrity", 422)
                blob = artifact.source_blob or shared_blob(db, raw, source["sha256"])
                fresh = Source(session_id=item.id, visual_page_id=source["visual_page_id"], source=source,
                    source_blob_id=blob.id)
                db.add(fresh)
                db.flush()
                prior = db.scalar(select(Source).join(ExtractionSession, Source.session_id == ExtractionSession.id).where(
                    ExtractionSession.revision_id == revision.id, ExtractionSession.scope_key == scope,
                    Source.visual_page_id == fresh.visual_page_id, Source.id != fresh.id).order_by(Source.id.desc()).limit(1))
                if prior and all(prior.source.get(k) == source.get(k) for k in ("sha256", "page_number", "artifact_id")):
                    carry_forward(db, actor, prior, fresh)
        db.flush()
        add_audit_log(db, actor, "catalog_extraction_session", item.id, "EXTRACTION_SELECTION_RECORDED",
            {"revision_id": revision.id, "selection_digest": fingerprint, "sources": chosen})
    return item


def carry_forward(db, actor, prior, fresh):
    """Preserve corrections after selection edits, but never inherit approval."""
    identities = {}
    for candidate in candidates(db, prior):
        copied = Candidate(source_id=fresh.id, stable_key=candidate.stable_key,
            original=candidate.original, values=candidate.values, state=candidate.state,
            part_id=candidate.part_id, part_created_at=candidate.part_created_at,
            reason=candidate.reason, updated_by_id=actor.id)
        db.add(copied)
        db.flush()
        identities[candidate.id] = copied.id
    attempt = db.get(Attempt, prior.current_attempt_id) if prior.current_attempt_id else None
    if attempt and attempt.state == "SUCCEEDED":
        evidence = json.loads(json.dumps(attempt.evidence))
        for row in evidence["rows"]:
            row["candidate_id"] = identities[row["candidate_id"]]
        evidence["carried_from_attempt_id"] = attempt.id
        restored = Attempt(source_id=fresh.id, kind="CARRY_FORWARD", state="SUCCEEDED", extractor=attempt.extractor,
            actor_id=actor.id, deadline_at=utcnow(), finished_at=utcnow(), evidence=evidence,
            evidence_digest=hashed(evidence))
        db.add(restored)
        db.flush()
        fresh.current_attempt_id, fresh.processing_state = restored.id, "SUCCEEDED"
    fresh.review_state = "NEEDS_REVIEW"
    add_audit_log(db, actor, "catalog_extraction_source", fresh.id, "EXTRACTION_WORK_RESUMED",
        {"previous_source_id": prior.id, "candidate_count": len(identities)})


def source_context(db, visual_page_id, actor=None, *, create=False, mutate=False):
    page = db.get(CatalogRevisionVisualPage, visual_page_id)
    if page is None or page.role != "SPARE_PARTS_LIST":
        raise fail("catalog_part_page_invalid", 422)
    _, assembly, revision, catalog = visual_sources._artifact(db, page.artifact_id, mutate=mutate)
    page = db.scalar(select(CatalogRevisionVisualPage).where(CatalogRevisionVisualPage.id == visual_page_id)
        .execution_options(populate_existing=True))
    if page is None or page.role != "SPARE_PARTS_LIST":
        raise fail("catalog_part_page_invalid", 422)
    active = session(db, actor, assembly, revision, page.reference_page_id, create=create)
    source = db.scalar(select(Source).where(Source.session_id == active.id,
        Source.visual_page_id == page.id).execution_options(populate_existing=True)) if active else None
    return source, active, page, assembly, revision, catalog


def candidates(db, source):
    return list(db.scalars(select(Candidate).where(Candidate.source_id == source.id).order_by(Candidate.id)))


def accepted_part(db, candidate):
    """Integer tombstones must never resolve to a replacement SQLite row."""
    part = db.get(CatalogRevisionPart, candidate.part_id) if candidate.part_id else None
    return part if part and part.created_at == candidate.part_created_at else None


def scope_fingerprint(db, active):
    reference = db.get(CatalogRevisionReferencePage, active.reference_page_id) if active.reference_page_id else None
    parts = list(db.scalars(select(CatalogRevisionPart).where(
        CatalogRevisionPart.assembly_id == active.assembly_id,
        CatalogRevisionPart.reference_page_id == active.reference_page_id).order_by(CatalogRevisionPart.id)))
    maps = list(db.scalars(select(CatalogRevisionPartPageMap).where(
        CatalogRevisionPartPageMap.part_id.in_([p.id for p in parts])).order_by(CatalogRevisionPartPageMap.id)))
    return hashed({"selection": selection(db, active.assembly_id, active.reference_page_id),
        "reference_version": reference.version if reference else None,
        "parts": [{"id": p.id, "updated_at": str(p.updated_at), "evidence": p.extraction_evidence,
                   **{key: getattr(p, key) for key in PartCreate.model_fields}} for p in parts],
        "maps": [[m.id, m.part_id, m.visual_page_id] for m in maps]})


def fingerprint(db, source, active, *, scope_digest=None):
    attempt = db.get(Attempt, source.current_attempt_id) if source.current_attempt_id else None
    return hashed({"scope": scope_digest or scope_fingerprint(db, active),
        "source": source.source, "source_blob_id": source.source_blob_id,
        "attempt": {"id": attempt.id, "state": attempt.state,
            "evidence_digest": attempt.evidence_digest, "extractor": attempt.extractor} if attempt else None,
        "processing": source.processing_state,
        "candidates": [[c.id, c.version, c.state, c.part_id, c.part_created_at, c.values, c.reason] for c in candidates(db, source)]})


def valid(db, source, active, *, scope_digest=None):
    if (source is None or source.review_state != "VERIFIED" or source.reviewed_by_id is None
            or source.reviewed_at is None or source.processing_state != "SUCCEEDED"
            or any(c.state in {"PENDING", "CONFLICT"} or c.state == "ACCEPTED" and not accepted_part(db, c)
                for c in candidates(db, source))):
        return False
    attempt = db.get(Attempt, source.current_attempt_id) if source.current_attempt_id else None
    if (attempt is None or attempt.source_id != source.id or attempt.state != "SUCCEEDED"
            or attempt.finished_at is None or not attempt.evidence
            or hashed(attempt.evidence) != attempt.evidence_digest):
        return False
    decision = db.scalar(select(Decision).where(Decision.source_id == source.id)
        .order_by(Decision.id.desc()).limit(1))
    current = fingerprint(db, source, active, scope_digest=scope_digest)
    return bool(decision and decision.source_version == source.version
        and decision.fingerprint == source.approved_fingerprint == current
        and decision.actor_id == source.reviewed_by_id and decision.created_at == source.reviewed_at)


def publication_state(db, content):
    """Called after the catalog lock by publish; also supplies the digest proof."""
    errors, proof, scopes = [], [], {}
    assemblies = {a.id: a for a in content["assemblies"]}
    artifacts = {a.id: a for a in content["artifacts"]}
    from ...models import CatalogRevision
    for page in content["pages"]:
        if page.role != "SPARE_PARTS_LIST":
            continue
        assembly = assemblies[artifacts[page.artifact_id].assembly_id]
        revision = db.get(CatalogRevision, assembly.revision_id)
        scope = (assembly.id, page.reference_page_id)
        if scope not in scopes:
            active = session(db, None, assembly, revision, page.reference_page_id)
            scopes[scope] = (active, scope_fingerprint(db, active) if active else None)
        active, scope_digest = scopes[scope]
        source = db.scalar(select(Source).where(Source.session_id == active.id,
            Source.visual_page_id == page.id)) if active else None
        approved = valid(db, source, active, scope_digest=scope_digest) if source else False
        if not approved:
            errors.append({"code": "catalog_publication_source_review_required", "visual_page_id": page.id,
                "assembly_id": assembly.id, "reference_page_id": page.reference_page_id})
        proof.append({"visual_page_id": page.id, "session_id": active.id if active else None,
            "source_id": source.id if source else None, "version": source.version if source else None,
            "fingerprint": fingerprint(db, source, active, scope_digest=scope_digest) if source else None,
            "approved_fingerprint": source.approved_fingerprint if source else None, "valid": approved})
    return errors, proof


def invalidate(source):
    source.version += 1
    source.review_state = "NEEDS_REVIEW"
    # Keep the previous decision/fingerprint for audit and stale-state diagnostics.


def invalidate_scope(db, actor, assembly_id, reference_page_id, cause):
    """Monotonic invalidation also prevents approval revival after a reverted edit.

    Include inactive selection sessions: SQLite may reuse deleted integer IDs.
    Decisions/attempts remain immutable; only their applicability is revoked.
    """
    sources = list(db.scalars(select(Source).join(ExtractionSession, Source.session_id == ExtractionSession.id).where(
        ExtractionSession.assembly_id == assembly_id, ExtractionSession.reference_page_id == reference_page_id,
        Source.review_state == "VERIFIED").execution_options(populate_existing=True)))
    for source in sources:
        invalidate(source)
        add_audit_log(db, actor, "catalog_extraction_source", source.id, "SOURCE_REVIEW_INVALIDATED",
            {"cause": cause, "approved_fingerprint": source.approved_fingerprint, "version": source.version})


def recover(db, actor, source):
    if source.processing_state != "RUNNING":
        return
    attempt = db.get(Attempt, source.current_attempt_id)
    if attempt and attempt.deadline_at < utcnow():
        attempt.state, attempt.finished_at, attempt.error_code = "CANCELLED", utcnow(), "catalog_extraction_interrupted"
        source.processing_state = "CANCELLED"
        invalidate(source)
        add_audit_log(db, actor, "catalog_extraction_attempt", attempt.id, "EXTRACTION_INTERRUPTED",
            {"source_id": source.id})


def start(db, actor, source, extractor):
    recover(db, actor, source)
    if source.processing_state == "RUNNING":
        raise fail("catalog_extraction_busy")
    attempt = Attempt(source_id=source.id, state="RUNNING", extractor=extractor, actor_id=actor.id,
        deadline_at=utcnow() + timedelta(seconds=settings.catalog_extraction_page_timeout_seconds + 30))
    db.add(attempt)
    db.flush()
    source.current_attempt_id, source.processing_state = attempt.id, "RUNNING"
    invalidate(source)
    add_audit_log(db, actor, "catalog_extraction_attempt", attempt.id, "EXTRACTION_STARTED", {"source_id": source.id})
    return attempt


def row_key(row):
    # Geometry is evidence, not identity. Exact original cell values preserve variants.
    return hashed(row["payload"])


def reconcile(db, actor, source, evidence, active):
    previous = candidates(db, source)
    known = {c.stable_key: c for c in previous}
    current_keys = [row_key(row) for row in evidence["rows"]]
    counts = Counter(current_keys)
    legacy = list(db.scalars(select(CatalogRevisionPart).join(CatalogRevisionPartPageMap,
        CatalogRevisionPartPageMap.part_id == CatalogRevisionPart.id).where(
        CatalogRevisionPartPageMap.visual_page_id == source.visual_page_id)))
    for row in evidence["rows"]:
        key = row_key(row)
        if key in known:
            candidate = known[key]
            if candidate.part_id and not accepted_part(db, candidate):
                candidate.state, candidate.reason = "CONFLICT", "ACCEPTED_PART_REMOVED"
                candidate.version += 1
        else:
            position = row["payload"].get("position")
            matching = [p for p in legacy if p.extraction_evidence
                and row_key(p.extraction_evidence["row"]) == key]
            competing = [c for c in previous if c.original["payload"].get("position") == position
                and c.stable_key not in current_keys]
            uncertain = competing or [p for p in legacy if p.position == position and p not in matching]
            candidate = Candidate(source_id=source.id, stable_key=key, original=row,
                values=row["payload"], state="ACCEPTED" if len(matching) == 1 else "CONFLICT" if uncertain or len(matching) > 1 else "PENDING",
                part_id=matching[0].id if len(matching) == 1 else None,
                part_created_at=matching[0].created_at if len(matching) == 1 else None,
                reason="SOURCE_ROW_CHANGED" if uncertain and not matching else None, updated_by_id=actor.id)
            db.add(candidate)
            db.flush()
            known[key] = candidate
        row["candidate_id"] = candidate.id
        if counts[key] > 1:
            candidate.state, candidate.reason = "CONFLICT", "DUPLICATE_SOURCE_ROW"
            candidate.version += 1
    # Disappearing unresolved rows must not silently disappear from the review task.
    for candidate in previous:
        if candidate.stable_key not in current_keys and candidate.state == "PENDING":
            candidate.state, candidate.reason = "CONFLICT", "SOURCE_ROW_DISAPPEARED"
            candidate.version += 1
    return evidence


def finish(db, actor, source, active, attempt, evidence):
    attempt.finished_at = utcnow()
    if evidence.get("error"):
        attempt.state = source.processing_state = "FAILED"
        attempt.error_code = evidence["error"]
    else:
        attempt.state = source.processing_state = "SUCCEEDED"
        attempt.evidence = reconcile(db, actor, source, evidence, active)
        attempt.evidence_digest = hashed(attempt.evidence)
    invalidate(source)
    add_audit_log(db, actor, "catalog_extraction_attempt", attempt.id, "EXTRACTION_FINISHED",
        {"source_id": source.id, "state": attempt.state, "error_code": attempt.error_code,
         "evidence_digest": attempt.evidence_digest, "row_count": len(evidence.get("rows", []))})


def serialize(db, source, active):
    attempts = list(db.scalars(select(Attempt).where(Attempt.source_id == source.id).order_by(Attempt.id)))
    return {"id": source.id, "visual_page_id": source.visual_page_id, "source": source.source,
        "version": source.version, "processing_state": source.processing_state,
        "review_state": "VERIFIED" if valid(db, source, active) else "NOT_REVIEWED" if source.review_state == "NOT_REVIEWED" else "NEEDS_REVIEW",
        "fingerprint": fingerprint(db, source, active), "reviewed_by_id": source.reviewed_by_id,
        "reviewed_at": source.reviewed_at, "attempts": [{"id": a.id, "state": a.state, "kind": a.kind,
            "started_at": a.started_at, "finished_at": a.finished_at, "error_code": a.error_code,
            "evidence_digest": a.evidence_digest, "row_count": len((a.evidence or {}).get("rows", []))} for a in attempts],
        "candidates": [{"id": c.id, "version": c.version, "state": c.state, "part_id": c.part_id,
            "values": c.values, "reason": c.reason, "original": c.original} for c in candidates(db, source)]}
