"""Permissioned, paginated ingestion and review API."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from ...audit import add_audit_log
from ...database import get_db
from ...models import (
    CatalogIngestCandidate,
    CatalogIngestPage,
    CatalogIngestRun,
    CatalogSourceBlob,
    User,
)
from ...permissions import Permission, require_permission
from .. import visual_sources
from ..service import fail
from . import candidates, review, runs
from .schemas import BulkReview, CandidateReview

router = APIRouter(prefix="/api/admin/catalog-builder", tags=["catalog-builder"])
manager = require_permission(Permission.PARTS_MANAGE)


@router.post("/artifacts/{artifact_id}/analysis")
def start_analysis(artifact_id: int, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return runs.start(db, actor, artifact_id)


@router.get("/revisions/{revision_id}/analyses")
def list_analysis(revision_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    visual_sources._revision(db, revision_id)
    return [candidates.summary(db, run) for run in db.scalars(select(CatalogIngestRun).where(
        CatalogIngestRun.revision_id == revision_id).order_by(CatalogIngestRun.id)).all()]


@router.get("/analyses/{run_id}")
def get_analysis(run_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return candidates.summary(db, runs.load_run(db, run_id))


@router.post("/analyses/{run_id}/advance")
def advance_analysis(run_id: int, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return runs.advance(db, actor, run_id)


@router.post("/analyses/{run_id}/retry")
def retry_analysis(run_id: int, rerun: bool = False, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return runs.retry(db, actor, run_id, rerun=rerun)


@router.post("/analyses/{run_id}/dismiss")
def dismiss_failed_analysis(run_id: int, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return runs.dismiss(db, actor, run_id)


@router.post("/analyses/{run_id}/match-hotspots")
def rematch_hotspots(run_id: int, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    run = runs.load_run(db, run_id, mutate=True)
    if run.status != "COMPLETED":
        raise fail("catalog_ingest_not_completed")
    candidates.match_hotspots(db, run)
    add_audit_log(db, actor, "catalog_ingest_run", run.id, "CATALOG_HOTSPOTS_REMATCHED",
                  {"sha256": run.sha256, "preserves_human_decisions": True})
    db.commit()
    return candidates.summary(db, run)


@router.get("/analyses/{run_id}/candidates")
def list_candidates(run_id: int,
    kind: Literal["GROUP", "PAGE", "PART", "HOTSPOT"],
    state: Literal["PROPOSED", "NEEDS_REVIEW", "ACCEPTED", "REJECTED"] | None = None,
    high_confidence: bool = False, search: str = Query(default="", max_length=120),
    errors: bool = False,
    match: Literal["EXACT", "MULTIPLE_CANDIDATES", "NOT_FOUND", "LOW_CONFIDENCE"] | None = None,
    verified: bool | None = None,
    after: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100),
    _: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    run = runs.load_run(db, run_id)
    query = select(CatalogIngestCandidate).where(CatalogIngestCandidate.run_id == run.id,
        CatalogIngestCandidate.kind == kind)
    if state:
        query = query.where(CatalogIngestCandidate.state == state)
    if high_confidence:
        query = query.where(CatalogIngestCandidate.confidence >= .9,
            CatalogIngestCandidate.state == "PROPOSED")
    if errors:
        query = query.where(or_(*(cast(CatalogIngestCandidate.warnings, String).contains(code)
            for code in ("MISSING_POSITION", "MISSING_PART_NUMBER", "MISSING_DESCRIPTION", "FIELD_TOO_LONG", "QUANTITY_UNCERTAIN"))))
    if match:
        query = query.where(CatalogIngestCandidate.payload["match"].as_string() == match)
    if verified is True:
        query = query.where(CatalogIngestCandidate.payload["verified"].as_boolean().is_(True))
    elif verified is False:
        query = query.where(or_(CatalogIngestCandidate.payload["verified"].as_boolean().is_(None),
                               CatalogIngestCandidate.payload["verified"].as_boolean().is_(False)))
    if search:
        # Portable JSON string search with escaped wildcards; no SQL interpolation.
        query = query.where(cast(CatalogIngestCandidate.payload, String).icontains(search, autoescape=True))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.where(CatalogIngestCandidate.id > after)
        .order_by(CatalogIngestCandidate.id).limit(limit + 1)).all()
    return {"items": [candidates.candidate_dict(item, run) for item in rows[:limit]],
            "total": total, "next_after": rows[limit - 1].id if len(rows) > limit else None}


@router.get("/analyses/{run_id}/pages/{number}")
def page_evidence(run_id: int, number: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    run = runs.load_run(db, run_id)
    page = db.scalar(select(CatalogIngestPage).where(CatalogIngestPage.run_id == run.id,
        CatalogIngestPage.page_number == number))
    if page is None:
        raise fail("catalog_visual_page_invalid", 404)
    return {"sha256": run.sha256, "page_number": number, "evidence": page.evidence}


@router.get("/analyses/{run_id}/pages/{number}/preview")
def preview_evidence(run_id: int, number: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> Response:
    import base64

    from ...settings import settings
    from .process import configuration, extract

    run = runs.load_run(db, run_id)
    if not 1 <= number <= run.page_count:
        raise fail("catalog_visual_page_invalid", 404)
    content = db.get(CatalogSourceBlob, run.source_blob_id).content
    result = extract(content, "preview", number, configuration(settings))
    if result.get("error"):
        raise fail("catalog_source_invalid_pdf", 422)
    return Response(base64.b64decode(result["image"]), media_type="image/png",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/analyses/{run_id}/candidates/{candidate_id}/review")
def review_candidate(run_id: int, candidate_id: int, data: CandidateReview,
                     actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return review.review_one(db, actor, run_id, candidate_id, data)


@router.post("/analyses/{run_id}/bulk-review")
def bulk_review(run_id: int, data: BulkReview, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return review.bulk(db, actor, run_id, data)
