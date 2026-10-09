"""Permissioned reference-page editing and selected-list preview/confirm API."""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..permissions import Permission, require_permission
from . import hotspots, parts, reference_pages, visual_sources
from .parts_extraction import review
from .parts_extraction import service as extraction
from .parts_extraction.schemas import (
    CandidateEdit,
    ColumnMapping,
    ExtractConfirm,
    ExtractSelection,
    PageCreate,
    PageOrder,
    PageUpdate,
    ReferenceOrder,
    SourceAssign,
    SourceOrder,
    SourceReview,
)
from .schemas import PartCreate, PartImportConfirm, PartImportPreview

router = APIRouter(prefix="/api/admin/catalog-builder", tags=["catalog-builder"])
manager = require_permission(Permission.PARTS_MANAGE)


@router.post("/reference-pages/{page_id}/review-session")
def resume_review(page_id: int, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    page, assembly, *_ = reference_pages.load(db, page_id)
    return review.workspace(db, actor, assembly.id, page.id)


@router.post("/assemblies/{assembly_id}/source-review")
def resume_legacy_review(assembly_id: int, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return review.workspace(db, actor, assembly_id)


@router.get("/visual-pages/{source_id}/review-original")
def review_original(source_id: int, actor: User = Depends(manager), db: Session = Depends(get_db)) -> Response:
    image, receipt = review.original(db, actor, source_id)
    return Response(image, media_type="image/png", headers={"Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff", "X-Catalog-Review-Receipt": receipt})


@router.post("/visual-pages/{source_id}/review")
def verify_source(source_id: int, data: SourceReview, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return review.verify(db, actor, source_id, data)


@router.get("/extraction-sources/{source_id}/original")
def historical_source_original(source_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> Response:
    return Response(review.historical_original(db, source_id), media_type="image/png",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/visual-pages/{source_id}/selection-correction", status_code=204)
def correct_selection(source_id: int, data: SourceReview, actor: User = Depends(manager), db: Session = Depends(get_db)) -> None:
    review.correct_selection(db, actor, source_id, data)


@router.patch("/extraction-candidates/{candidate_id}")
def edit_candidate(candidate_id: int, data: CandidateEdit, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return review.edit_candidate(db, actor, candidate_id, data)


@router.get("/assemblies/{assembly_id}/reference-pages")
def list_pages(assembly_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return reference_pages.list_pages(db, assembly_id)


@router.post("/assemblies/{assembly_id}/reference-pages", status_code=201)
def create_page(assembly_id: int, data: PageCreate, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return reference_pages.create(db, actor, assembly_id, data)


@router.patch("/reference-pages/{page_id}")
def update_page(page_id: int, data: PageUpdate, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return reference_pages.update(db, actor, page_id, data)


@router.delete("/reference-pages/{page_id}", status_code=204)
def delete_page(page_id: int, expected_version: int = Query(ge=1), actor: User = Depends(manager),
                db: Session = Depends(get_db)) -> None:
    reference_pages.delete_page(db, actor, page_id, expected_version)


@router.post("/reference-pages/{page_id}/sources")
def assign_sources(page_id: int, data: SourceAssign, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return reference_pages.assign(db, actor, page_id, data)


@router.delete("/reference-pages/{page_id}/sources/{source_id}", status_code=204)
def remove_source(page_id: int, source_id: int, expected_version: int = Query(ge=1),
                  actor: User = Depends(manager), db: Session = Depends(get_db)) -> None:
    page, _, _, _ = reference_pages.load(db, page_id, mutate=True)
    reference_pages.check_version(page, expected_version)
    if not any(source["id"] == source_id for source in reference_pages.assignments(db, page_id)):
        raise visual_sources.fail("catalog_visual_page_invalid", 422)
    visual_sources.remove_visual_page(db, actor, source_id)


@router.get("/reference-pages/{page_id}/parts")
def page_parts(page_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    page, assembly, _, _ = reference_pages.load(db, page_id)
    return parts.list_parts(db, assembly.id, reference_page_id=page.id)


@router.post("/reference-pages/{page_id}/parts", status_code=201)
def create_part(page_id: int, data: PartCreate, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    page, assembly, _, _ = reference_pages.load(db, page_id, mutate=True)
    return parts.create_part(db, actor, assembly.id, data, reference_page_id=page.id)


@router.get("/reference-pages/{page_id}/spare-list-pages")
def lists(page_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    page, assembly, _, _ = reference_pages.load(db, page_id)
    return parts.spare_list_pages(db, assembly.id, page.id)


@router.post("/reference-pages/{page_id}/parts/import-preview")
def csv_preview(page_id: int, data: PartImportPreview, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    page, assembly, _, _ = reference_pages.load(db, page_id, mutate=True)
    return parts.import_preview(db, actor, assembly.id, data, page.id)


@router.post("/reference-pages/{page_id}/parts/import-confirm")
def csv_confirm(page_id: int, data: PartImportConfirm, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    page, assembly, _, _ = reference_pages.load(db, page_id, mutate=True)
    return parts.import_confirm(db, actor, assembly.id, data.token, data.confirm_warnings, page.id)


@router.get("/reference-pages/{page_id}/coverage")
def coverage(page_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    page, assembly, _, _ = reference_pages.load(db, page_id)
    return hotspots.coverage(db, assembly.id, reference_page_id=page.id)


@router.get("/reference-pages/{page_id}/exploded-pages")
def schemes(page_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    page, assembly, _, _ = reference_pages.load(db, page_id)
    ids = {source["id"] for source in reference_pages.assignments(db, page.id)}
    return [source for source in hotspots.exploded_pages(db, assembly.id) if source["visual_page_id"] in ids]


@router.post("/reference-pages/{page_id}/extract")
def preview(page_id: int, data: ExtractSelection, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return extraction.preview(db, actor, page_id, data)


@router.post("/reference-pages/{page_id}/extraction/mapping")
def mapping(page_id: int, data: ColumnMapping, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return extraction.remap(db, actor, page_id, data)


@router.post("/reference-pages/{page_id}/extraction/confirm")
def confirm(page_id: int, data: ExtractConfirm, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return extraction.confirm(db, actor, page_id, data)


@router.post("/assemblies/{assembly_id}/reference-pages/reorder")
def reorder_pages(assembly_id: int, data: PageOrder, actor: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return reference_pages.reorder_pages(db, actor, assembly_id, data)


@router.post("/revisions/{revision_id}/references/reorder")
def reorder_references(revision_id: int, data: ReferenceOrder, actor: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return reference_pages.reorder_references(db, actor, revision_id, data)


@router.post("/reference-pages/{page_id}/sources/reorder")
def reorder_sources(page_id: int, data: SourceOrder, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return reference_pages.reorder_sources(db, actor, page_id, data)
