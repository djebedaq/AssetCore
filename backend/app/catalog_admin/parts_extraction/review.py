"""Permissioned resume, original inspection and explicit human decisions."""
import base64
import hashlib
import hmac
import json
import time

from sqlalchemy import select

from ...audit import add_audit_log
from ...models import CatalogRevisionPart, CatalogRevisionPartPageMap, CatalogSourceBlob
from ...settings import settings
from .. import reference_pages, visual_sources
from ..service import fail
from . import ledger, service


def workspace(db, actor, assembly_id, reference_page_id=None):
    assembly, revision, _ = visual_sources._assembly(db, assembly_id, mutate=True)
    if reference_page_id is not None:
        page, *_ = reference_pages.load(db, reference_page_id, mutate=True)
        if page.assembly_id != assembly.id:
            raise fail("catalog_part_page_invalid", 422)
    active = ledger.session(db, actor, assembly, revision, reference_page_id, create=True)
    sources = list(db.scalars(select(ledger.Source).where(ledger.Source.session_id == active.id).order_by(ledger.Source.id)))
    result = []
    for source in sources:
        ledger.recover(db, actor, source)
        for candidate in ledger.candidates(db, source):
            if candidate.state == "ACCEPTED" and not ledger.accepted_part(db, candidate):
                candidate.state, candidate.reason = "CONFLICT", "ACCEPTED_PART_REMOVED"
                candidate.version += 1
                ledger.invalidate(source)
                add_audit_log(db, actor, "catalog_extraction_candidate", candidate.id, "EXTRACTION_LINK_INVALIDATED",
                    {"source_id": source.id, "part_id": candidate.part_id})
        db.flush()
        item = ledger.serialize(db, source, active)
        attempt = service.resumable_attempt(db, source)
        item["preview"] = service._result(service.claim_for(db, actor, page, source, active, attempt), db) if (
            reference_page_id is not None and attempt and attempt.state == "SUCCEEDED") else None
        result.append(item)
    db.commit()
    return {"id": active.id, "selection_digest": active.selection_digest, "sources": result}


def original(db, actor, visual_page_id):
    source, active, page, *_ = ledger.source_context(db, visual_page_id, actor, create=True, mutate=True)
    artifact = db.get(ledger.CatalogRevisionArtifact, page.artifact_id)
    if hashlib.sha256(artifact.content).hexdigest() != artifact.sha256:
        raise fail("catalog_source_invalid", 422)
    image = visual_sources.preview_page(db, page.artifact_id, page.page_number)
    claim = {"purpose": "SOURCE_REVIEW", "actor_id": actor.id, "source_id": source.id,
        "session_id": active.id, "version": source.version, "fingerprint": ledger.fingerprint(db, source, active),
        "created": int(time.time())}
    token = service._sign(claim)
    add_audit_log(db, actor, "catalog_extraction_source", source.id, "SOURCE_ORIGINAL_INSPECTED",
        {"fingerprint": claim["fingerprint"], "inspection_digest": ledger.hashed(token)})
    db.commit()
    return image, token


def historical_original(db, source_id):
    source = db.get(ledger.Source, source_id)
    if source is None:
        raise fail("catalog_part_page_invalid", 404)
    active = db.get(ledger.ExtractionSession, source.session_id)
    visual_sources._revision(db, active.revision_id)
    blob = db.get(CatalogSourceBlob, source.source_blob_id)
    if blob is None or hashlib.sha256(blob.content).hexdigest() != source.source["sha256"]:
        raise fail("catalog_source_integrity", 422)
    result = service.process.extract(blob.content, "preview", source.source["page_number"],
        service.process.configuration(settings))
    if result.get("error"):
        raise fail("catalog_source_invalid_pdf", 422)
    return base64.b64decode(result["image"])


def inspected(db, actor, source, active, data):
    current = ledger.fingerprint(db, source, active)
    if data.expected_version != source.version or data.fingerprint != current:
        raise fail("catalog_reference_page_stale")
    try:
        encoded, signature = data.inspection_token.split(".", 1)
        raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        expected = hmac.new(settings.secret_key.encode(), raw, hashlib.sha256).hexdigest()
        claim = json.loads(raw)
        if (not hmac.compare_digest(signature, expected) or claim["purpose"] != "SOURCE_REVIEW"
                or claim["actor_id"] != actor.id or claim["source_id"] != source.id
                or claim["session_id"] != active.id or claim["version"] != source.version
                or claim["fingerprint"] != current or not 0 <= time.time() - claim["created"] <= 900):
            raise ValueError("binding")
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise fail("catalog_source_review_inspection_required", 422) from None
    if len(data.reason.strip()) < 10:
        raise fail("catalog_source_review_reason_required", 422)


def correct_selection(db, actor, visual_page_id, data):
    source, active, page, *_ = ledger.source_context(db, visual_page_id, actor, create=True, mutate=True)
    inspected(db, actor, source, active, data)
    if source.processing_state == "RUNNING" or any(c.state != "REJECTED" for c in ledger.candidates(db, source)):
        raise fail("catalog_source_review_incomplete", 422)
    if db.scalar(select(CatalogRevisionPartPageMap.id).where(CatalogRevisionPartPageMap.visual_page_id == page.id).limit(1)):
        raise fail("catalog_reference_source_in_use")
    add_audit_log(db, actor, "catalog_extraction_source", source.id, "SOURCE_SELECTION_CORRECTED",
        {"classification": "WRONG_SELECTION", "reason": data.reason.strip(), "source": source.source,
         "fingerprint": data.fingerprint, "inspection_digest": ledger.hashed(data.inspection_token),
         "selection_digest": active.selection_digest})
    visual_sources.remove_visual_page(db, actor, page.id, reviewed_correction=True)


def verify(db, actor, visual_page_id, data):
    source, active, *_ = ledger.source_context(db, visual_page_id, actor, create=True, mutate=True)
    inspected(db, actor, source, active, data)
    unresolved = any(c.state in {"PENDING", "CONFLICT"} for c in ledger.candidates(db, source))
    for candidate in ledger.candidates(db, source):
        if candidate.state == "ACCEPTED" and (not ledger.accepted_part(db, candidate) or not db.scalar(select(CatalogRevisionPartPageMap.id).where(
                CatalogRevisionPartPageMap.part_id == candidate.part_id,
                CatalogRevisionPartPageMap.visual_page_id == visual_page_id))):
            unresolved = True
    mapped = db.scalar(select(CatalogRevisionPart.id).join(CatalogRevisionPartPageMap,
        CatalogRevisionPartPageMap.part_id == CatalogRevisionPart.id).where(
        CatalogRevisionPartPageMap.visual_page_id == visual_page_id,
        CatalogRevisionPart.assembly_id == active.assembly_id,
        CatalogRevisionPart.reference_page_id == active.reference_page_id).limit(1))
    attempt = db.get(ledger.Attempt, source.current_attempt_id) if source.current_attempt_id else None
    zero = not attempt or not (attempt.evidence or {}).get("rows")
    if source.processing_state == "RUNNING" or unresolved or mapped is None:
        raise fail("catalog_source_review_incomplete", 422)
    if (zero or source.processing_state != "SUCCEEDED") and not data.manual_transcription:
        raise fail("catalog_source_review_manual_required", 422)
    if not data.reason.strip() or len(data.reason.strip()) < 10:
        raise fail("catalog_source_review_reason_required", 422)
    # A failed/zero OCR page can only be completed by explicit transcription with
    # mapped parts and an inspected original, never by excluding it from the gate.
    if data.manual_transcription and (zero or source.processing_state != "SUCCEEDED"):
        attempt = ledger.start(db, actor, source, service.EXTRACTOR_VERSION)
        attempt.kind = "MANUAL"
        ledger.finish(db, actor, source, active, attempt,
            {"rows": [], "tables": [], "warnings": ["MANUAL_TRANSCRIPTION"], "method": "MANUAL"})
    final = ledger.fingerprint(db, source, active)
    source.review_state, source.approved_fingerprint = "VERIFIED", final
    source.reviewed_by_id, source.reviewed_at = actor.id, ledger.utcnow()
    source.version += 1
    decision = ledger.Decision(source_id=source.id, source_version=source.version, fingerprint=final,
        decision="VERIFIED", reason=data.reason.strip(), inspection_digest=ledger.hashed(data.inspection_token),
        actor_id=actor.id, created_at=source.reviewed_at)
    db.add(decision)
    db.flush()
    add_audit_log(db, actor, "catalog_extraction_source", source.id, "SOURCE_REVIEW_VERIFIED",
        {"decision_id": decision.id, "fingerprint": final, "reason": decision.reason,
         "manual_transcription": data.manual_transcription})
    result = ledger.serialize(db, source, active)
    db.commit()
    return result


def edit_candidate(db, actor, candidate_id, data):
    candidate = db.get(ledger.Candidate, candidate_id)
    if candidate is None:
        raise fail("catalog_extraction_candidate_not_found", 404)
    historical = db.get(ledger.Source, candidate.source_id)
    source, active, *_ = ledger.source_context(db, historical.visual_page_id, actor, create=True, mutate=True)
    db.refresh(candidate)
    if candidate.source_id != source.id or candidate.version != data.expected_version:
        raise fail("catalog_reference_page_stale")
    if source.processing_state == "RUNNING" or candidate.state == "ACCEPTED":
        raise fail("catalog_extraction_candidate_unresolved")
    before = {"values": candidate.values, "state": candidate.state, "reason": candidate.reason}
    if data.action in {"REJECT", "LINK_EXISTING", "NEW_VARIANT"} and (not data.reason or len(data.reason.strip()) < 10):
        raise fail("catalog_source_review_reason_required", 422)
    if data.action == "SAVE":
        if candidate.state == "CONFLICT" or data.values is None:
            raise fail("catalog_extraction_candidate_unresolved")
        if set(data.values) - set(ledger.PartCreate.model_fields) or len(json.dumps(data.values)) > 20000:
            raise fail("catalog_part_invalid", 422)
        try:
            json.dumps(data.values, allow_nan=False)
        except ValueError:
            raise fail("catalog_part_invalid", 422) from None
        candidate.values = data.values
    elif data.action == "LINK_EXISTING":
        part = db.scalar(select(CatalogRevisionPart).join(CatalogRevisionPartPageMap,
            CatalogRevisionPartPageMap.part_id == CatalogRevisionPart.id).where(
            CatalogRevisionPart.id == data.part_id, CatalogRevisionPartPageMap.visual_page_id == source.visual_page_id,
            CatalogRevisionPart.assembly_id == active.assembly_id,
            CatalogRevisionPart.reference_page_id == active.reference_page_id))
        if part is None:
            raise fail("catalog_part_page_invalid", 422)
        candidate.part_id, candidate.state = part.id, "ACCEPTED"
        candidate.part_created_at = part.created_at
    elif data.action == "NEW_VARIANT":
        if candidate.state != "CONFLICT":
            raise fail("catalog_extraction_candidate_unresolved")
        candidate.state = "PENDING"
    elif data.action == "REJECT":
        candidate.state = "REJECTED"
    elif data.action == "RESTORE":
        if candidate.state != "REJECTED":
            raise fail("catalog_extraction_candidate_unresolved")
        candidate.state = "CONFLICT"  # Restoring a rejection always requires an explicit reconciliation decision.
    candidate.reason = data.reason or candidate.reason
    candidate.version += 1
    candidate.updated_by_id, candidate.updated_at = actor.id, ledger.utcnow()
    ledger.invalidate(source)
    add_audit_log(db, actor, "catalog_extraction_candidate", candidate.id, "EXTRACTION_CANDIDATE_REVIEWED",
        {"action": data.action, "before": before, "after": {"values": candidate.values,
         "state": candidate.state, "reason": candidate.reason}, "source_id": source.id})
    db.commit()
    return {"id": candidate.id, "version": candidate.version, "state": candidate.state}
