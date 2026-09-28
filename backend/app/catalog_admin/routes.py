"""Permissioned administration API for Builder workspaces."""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..permissions import Permission, require_permission
from . import repository, service
from .schemas import CatalogCreate, CatalogUpdate, RevisionCreate, RevisionUpdate

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
