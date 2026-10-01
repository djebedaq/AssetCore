"""Leased, resumable processing. Database checkpoints survive browser/process loss."""

from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...audit import add_audit_log
from ...models import (
    CatalogIngestCandidate,
    CatalogIngestPage,
    CatalogIngestRun,
    CatalogSourceBlob,
    utcnow,
)
from ...settings import settings
from .. import visual_sources
from ..service import fail
from ..source_storage import shared_blob
from . import candidates, process


def load_run(db: Session, run_id: int, *, mutate: bool = False) -> CatalogIngestRun:
    run = db.get(CatalogIngestRun, run_id)
    if run is None:
        raise fail("catalog_ingest_not_found", 404)
    visual_sources._revision(db, run.revision_id, mutate=mutate)
    return db.scalar(select(CatalogIngestRun).where(CatalogIngestRun.id == run_id)
        .execution_options(populate_existing=True))


def start(db: Session, actor, artifact_id: int) -> dict:
    artifact, _, revision, _ = visual_sources._artifact(db, artifact_id, mutate=True)
    run = db.scalar(select(CatalogIngestRun).where(CatalogIngestRun.revision_id == revision.id,
        CatalogIngestRun.sha256 == artifact.sha256,
        CatalogIngestRun.extractor_version == candidates.EXTRACTOR_VERSION))
    if run is None:
        blob = artifact.source_blob or shared_blob(db, artifact.content, artifact.sha256)
        run = CatalogIngestRun(revision_id=revision.id, source_blob_id=blob.id,
            artifact_id=artifact.id, sha256=artifact.sha256, page_count=artifact.page_count,
            extractor_version=candidates.EXTRACTOR_VERSION, created_by_id=actor.id, context={})
        db.add(run)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            run = db.scalar(select(CatalogIngestRun).where(CatalogIngestRun.revision_id == revision.id,
                CatalogIngestRun.sha256 == artifact.sha256,
                CatalogIngestRun.extractor_version == candidates.EXTRACTOR_VERSION))
            if run is None:
                raise fail("catalog_ingest_stale") from None
            return candidates.summary(db, run)
        add_audit_log(db, actor, "catalog_ingest_run", run.id, "CATALOG_ANALYSIS_STARTED",
                      {"revision_id": revision.id, "sha256": run.sha256, "extractor_version": run.extractor_version})
    db.commit()
    return candidates.summary(db, run)


def advance(db: Session, actor, run_id: int) -> dict:
    run = load_run(db, run_id, mutate=True)
    if run.status != "RUNNING":
        db.commit()
        return candidates.summary(db, run)
    token = str(uuid4())
    now = utcnow()
    claimed = db.execute(update(CatalogIngestRun).where(CatalogIngestRun.id == run.id,
        or_(CatalogIngestRun.claim_token.is_(None), CatalogIngestRun.claim_expires_at < now))
        .values(claim_token=token, claim_expires_at=now + timedelta(seconds=settings.catalog_ingest_page_timeout_seconds + 30)))
    if claimed.rowcount != 1:
        db.rollback()
        return candidates.summary(db, run)
    number = run.next_page
    db.commit()
    try:
        cached = db.scalar(select(CatalogIngestPage).where(CatalogIngestPage.run_id == run.id,
            CatalogIngestPage.page_number == number))
        if cached:
            layout = cached.evidence
        else:
            blob = db.get(CatalogSourceBlob, run.source_blob_id)
            content = blob.content
            db.rollback()  # No transaction/row lock during native parsing or OCR.
            layout = process.extract(content, "page", number, process.configuration(settings))
        if layout.get("error"):
            raise fail(layout["error"], 422)
        run = load_run(db, run_id, mutate=True)
        if run.claim_token != token or run.next_page != number:
            raise fail("catalog_ingest_busy")
        if cached is None:
            db.add(CatalogIngestPage(run_id=run.id, page_number=number, evidence=layout))
        candidates.store_page(db, run, number, layout)
        run.context = {**run.context, "ocr_pages": run.context.get("ocr_pages", 0) + int(layout["ocr_used"])}
        run.next_page = number + 1
        run.claim_token = None
        run.claim_expires_at = None
        if run.next_page > run.page_count:
            candidates.match_hotspots(db, run)
            run.status = "COMPLETED"
            add_audit_log(db, actor, "catalog_ingest_run", run.id, "CATALOG_ANALYSIS_COMPLETED",
                {"sha256": run.sha256, "extractor_version": run.extractor_version,
                 "page_count": run.page_count, "ocr_pages": run.context["ocr_pages"]})
        db.commit()
    except Exception as exc:
        db.rollback()
        # A publication/retirement race must never mutate the now immutable revision.
        run = load_run(db, run_id, mutate=True)
        if run.claim_token == token:
            code = exc.detail.get("code", "catalog_ingest_failed") if isinstance(exc, HTTPException) and isinstance(exc.detail, dict) else "catalog_ingest_failed"
            run.status = "RUNNING" if code == "catalog_ingest_busy" else "FAILED"
            run.error_code = None if code == "catalog_ingest_busy" else code
            run.claim_token = None
            run.claim_expires_at = None
            if run.status == "FAILED":
                add_audit_log(db, actor, "catalog_ingest_run", run.id, "CATALOG_ANALYSIS_FAILED",
                              {"page_number": number, "error_code": run.error_code})
            db.commit()
    return candidates.summary(db, run)


def retry(db: Session, actor, run_id: int, *, rerun: bool = False) -> dict:
    run = load_run(db, run_id, mutate=True)
    if run.status == "COMPLETED" and not rerun:
        db.commit()
        return candidates.summary(db, run)
    if run.claim_token and run.claim_expires_at and run.claim_expires_at >= utcnow():
        raise fail("catalog_ingest_busy")
    if rerun:
        run.next_page = 1
        run.context = {}
    run.status = "RUNNING"
    run.error_code = None
    run.claim_token = None
    run.claim_expires_at = None
    add_audit_log(db, actor, "catalog_ingest_run", run.id, "CATALOG_ANALYSIS_RERUN" if rerun else "CATALOG_ANALYSIS_RETRIED",
                  {"sha256": run.sha256, "preserves_human_decisions": True})
    db.commit()
    return candidates.summary(db, run)


def dismiss(db: Session, actor, run_id: int) -> dict:
    """Explicit human rejection of a failed automatic pass; manual gates remain."""
    run = load_run(db, run_id, mutate=True)
    if run.status != "FAILED":
        raise fail("catalog_ingest_invalid")
    rows = db.scalars(select(CatalogIngestCandidate).where(CatalogIngestCandidate.run_id == run.id,
        CatalogIngestCandidate.state.in_(["PROPOSED", "NEEDS_REVIEW"])).order_by(CatalogIngestCandidate.id)
        .with_for_update()).all()
    for row in rows:
        row.state = "REJECTED"
        row.version += 1
        row.reviewed_by_id, row.reviewed_at = actor.id, utcnow()
    run.status = "DISMISSED"
    add_audit_log(db, actor, "catalog_ingest_run", run.id, "CATALOG_ANALYSIS_DISMISSED",
                  {"rejected_candidate_count": len(rows), "error_code": run.error_code,
                   "accepted_data_preserved": True, "manual_publication_checks_required": True})
    db.commit()
    return candidates.summary(db, run)
