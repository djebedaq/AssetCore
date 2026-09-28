"""Permissioned administration API for Builder workspaces."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..permissions import Permission, require_permission
from . import repository, service, visual_sources
from .schemas import (
    ArtifactUpload,
    AssemblyCreate,
    AssemblyUpdate,
    CatalogCreate,
    CatalogUpdate,
    RevisionCreate,
    RevisionUpdate,
    VisualPageCreate,
)

router = APIRouter(prefix="/api/admin/catalog-builder", tags=["catalog-builder"])
manager = require_permission(Permission.PARTS_MANAGE)


@router.get("/catalogs")
def list_catalogs(_: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return repository.catalogs(db)


@router.post("/catalogs", status_code=201)
def create_catalog(data: CatalogCreate, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return service.create_catalog(db, actor, data)


@router.get("/catalogs/{catalog_id}")
def get_catalog(catalog_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return service.catalog_dict(db, service.catalog(db, catalog_id))


@router.patch("/catalogs/{catalog_id}")
def update_catalog(catalog_id: int, data: CatalogUpdate, actor: User = Depends(manager),
                   db: Session = Depends(get_db)) -> dict:
    return service.update_catalog(db, actor, catalog_id, data)


@router.get("/catalogs/{catalog_id}/revisions")
def list_revisions(catalog_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return service.revisions(db, catalog_id)


@router.post("/catalogs/{catalog_id}/revisions", status_code=201)
def create_revision(catalog_id: int, data: RevisionCreate, actor: User = Depends(manager),
                    db: Session = Depends(get_db)) -> dict:
    return service.create_revision(db, actor, catalog_id, data)


@router.patch("/revisions/{revision_id}")
def update_revision(revision_id: int, data: RevisionUpdate, actor: User = Depends(manager),
                    db: Session = Depends(get_db)) -> dict:
    return service.update_revision(db, actor, revision_id, data)


@router.get("/catalogs/{catalog_id}/assets")
def list_assets(catalog_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    service.catalog(db, catalog_id)
    return repository.assets(db, catalog_id)


@router.get("/catalogs/{catalog_id}/eligible-assets")
def eligible_assets(catalog_id: int, search: str | None = Query(default=None, max_length=120),
                    _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return service.eligible_assets(db, catalog_id, search)


@router.post("/catalogs/{catalog_id}/assets/{machine_id}", status_code=201)
def bind_asset(catalog_id: int, machine_id: int, actor: User = Depends(manager),
               db: Session = Depends(get_db)) -> dict:
    return service.bind_asset(db, actor, catalog_id, machine_id)


@router.delete("/catalogs/{catalog_id}/assets/{machine_id}", status_code=204)
def unbind_asset(catalog_id: int, machine_id: int, actor: User = Depends(manager),
                 db: Session = Depends(get_db)) -> Response:
    service.unbind_asset(db, actor, catalog_id, machine_id)
    return Response(status_code=204)


@router.get("/revisions/{revision_id}/assemblies")
def list_assemblies(revision_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return visual_sources.list_assemblies(db, revision_id)


@router.post("/revisions/{revision_id}/assemblies", status_code=201)
def create_assembly(revision_id: int, data: AssemblyCreate, actor: User = Depends(manager),
                    db: Session = Depends(get_db)) -> dict:
    return visual_sources.create_assembly(db, actor, revision_id, data)


@router.patch("/assemblies/{assembly_id}")
def update_assembly(assembly_id: int, data: AssemblyUpdate, actor: User = Depends(manager),
                    db: Session = Depends(get_db)) -> dict:
    return visual_sources.update_assembly(db, actor, assembly_id, data)


@router.delete("/assemblies/{assembly_id}", status_code=204)
def delete_assembly(assembly_id: int, actor: User = Depends(manager), db: Session = Depends(get_db)) -> Response:
    visual_sources.delete_assembly(db, actor, assembly_id)
    return Response(status_code=204)


@router.get("/assemblies/{assembly_id}/artifacts")
def list_artifacts(assembly_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return visual_sources.list_artifacts(db, assembly_id)


@router.post("/assemblies/{assembly_id}/artifacts", status_code=201)
def upload_artifact(assembly_id: int, data: ArtifactUpload, actor: User = Depends(manager),
                    db: Session = Depends(get_db)) -> dict:
    return visual_sources.upload_artifact(db, actor, assembly_id, data)


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return visual_sources.get_artifact(db, artifact_id)


@router.delete("/artifacts/{artifact_id}", status_code=204)
def delete_artifact(artifact_id: int, actor: User = Depends(manager), db: Session = Depends(get_db)) -> Response:
    visual_sources.delete_artifact(db, actor, artifact_id)
    return Response(status_code=204)


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> Response:
    content, filename = visual_sources.download_artifact(db, artifact_id)
    return Response(content, media_type="application/pdf",
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                             "Content-Disposition": "attachment; filename=\"catalog-source.pdf\"; "
                             f"filename*=UTF-8''{quote(filename, safe='')}"})


@router.get("/artifacts/{artifact_id}/pages/{page_number}/preview")
def preview_artifact_page(artifact_id: int, page_number: int, _: User = Depends(manager),
                          db: Session = Depends(get_db)) -> Response:
    return Response(visual_sources.preview_page(db, artifact_id, page_number), media_type="image/png",
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/artifacts/{artifact_id}/visual-pages")
def list_visual_pages(artifact_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return visual_sources.list_visual_pages(db, artifact_id)


@router.post("/artifacts/{artifact_id}/visual-pages", status_code=201)
def assign_visual_pages(artifact_id: int, data: VisualPageCreate, actor: User = Depends(manager),
                        db: Session = Depends(get_db)) -> list[dict]:
    return visual_sources.assign_visual_pages(db, actor, artifact_id, data)


@router.delete("/visual-pages/{assignment_id}", status_code=204)
def remove_visual_page(assignment_id: int, actor: User = Depends(manager),
                       db: Session = Depends(get_db)) -> Response:
    visual_sources.remove_visual_page(db, actor, assignment_id)
    return Response(status_code=204)
