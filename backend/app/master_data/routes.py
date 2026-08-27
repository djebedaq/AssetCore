"""Reference-data HTTP adapters with the original route grouping and permissions."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..industrial_schemas import (
    CategoryCreate,
    CategoryFieldCreate,
    DepartmentCreate,
    DepartmentUpdate,
    LocationAdminCreate,
    LocationAdminUpdate,
)
from ..models import AssetCategory, CategoryFieldDefinition, Location, User
from ..permissions import Permission, require_permission
from ..schemas import LocationOut
from . import service

legacy_router = APIRouter(prefix="/api")
category_router = APIRouter()
router = APIRouter()
require_admin = require_permission(Permission.SETTINGS_MANAGE)
require_document_viewer = require_permission(Permission.DOCUMENTS_VIEW)


@legacy_router.get("/locations", response_model=list[LocationOut])
def locations(
    _: User = Depends(require_document_viewer), db: Session = Depends(get_db)
) -> list[Location]:
    return service.locations(_=_, db=db)


@category_router.get("/categories")
def list_categories(
    _: User = Depends(require_document_viewer), db: Session = Depends(get_db)
) -> list[dict]:
    return service.list_categories(_=_, db=db)


@category_router.post("/categories", status_code=201, response_model=None)
def create_category(
    payload: CategoryCreate,
    user: User = Depends(require_permission(Permission.ASSETS_CREATE)),
    db: Session = Depends(get_db),
) -> AssetCategory:
    return service.create_category(payload=payload, user=user, db=db)


@category_router.post("/categories/{category_id}/fields", status_code=201, response_model=None)
def create_category_field(
    category_id: int,
    payload: CategoryFieldCreate,
    user: User = Depends(require_permission(Permission.ASSETS_EDIT)),
    db: Session = Depends(get_db),
) -> CategoryFieldDefinition:
    return service.create_category_field(category_id=category_id, payload=payload, user=user, db=db)


@router.get("/departments")
def list_departments(
    _: User = Depends(require_document_viewer), db: Session = Depends(get_db)
) -> list[dict]:
    return service.list_departments(_=_, db=db)


@router.get("/admin/reference-data")
def admin_reference_data(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return service.admin_reference_data(_=_, db=db)


@router.post("/admin/locations", status_code=201)
def create_location(
    payload: LocationAdminCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    return service.create_location(payload=payload, user=user, db=db)


@router.patch("/admin/locations/{location_id}")
def update_location(
    location_id: int,
    payload: LocationAdminUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    return service.update_location(location_id=location_id, payload=payload, user=user, db=db)


@router.post("/admin/departments", status_code=201)
def create_department(
    payload: DepartmentCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    return service.create_department(payload=payload, user=user, db=db)


@router.patch("/admin/departments/{department_id}")
def update_department(
    department_id: int,
    payload: DepartmentUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    return service.update_department(department_id=department_id, payload=payload, user=user, db=db)
