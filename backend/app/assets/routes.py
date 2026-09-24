"""Asset HTTP adapters retaining legacy schemas, route names and permissions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..industrial_schemas import AttachmentCreate, CustomFieldValuesUpdate
from ..master_data.serializers import _category_field_dict
from ..models import AssetCategory, CategoryFieldDefinition, Machine, MachineFieldValue, User
from ..permissions import Permission, is_observer, require_permission
from ..schemas import MachineCreate, MachineOut, MachineUpdate
from . import attachments, custom_fields, passport, service, timeline
from .timeline_schemas import MachineTimelinePage, TimelineCategory

legacy_router = APIRouter(prefix="/api")
router = APIRouter()
require_asset_viewer = require_permission(Permission.ASSETS_VIEW)
require_document_viewer = require_permission(Permission.DOCUMENTS_VIEW)
require_document_generator = require_permission(Permission.DOCUMENTS_GENERATE)
require_repair_operator = require_permission(Permission.REPAIRS_EDIT)


@legacy_router.get("/machines", response_model=None)
def machines(
    category_id: int | None = Query(default=None, ge=1),
    user: User = Depends(require_asset_viewer), db: Session = Depends(get_db)
) -> list[Machine] | list[dict]:
    return service.machines(user=user, db=db, category_id=category_id)


@legacy_router.get("/machines/category-navigation")
def category_navigation(
    user: User = Depends(require_asset_viewer), db: Session = Depends(get_db)
) -> list[dict]:
    return service.category_navigation(user=user, db=db)


def _asset_form_category(db: Session, category_id: int) -> dict:
    category = db.get(AssetCategory, category_id)
    if category is None:
        raise HTTPException(404, detail={"code": "category_not_found", "message": "Категорията не е намерена."})
    fields = db.scalars(
        select(CategoryFieldDefinition).where(
            CategoryFieldDefinition.category_id == category_id,
            CategoryFieldDefinition.is_active.is_(True),
        ).order_by(CategoryFieldDefinition.sort_order, CategoryFieldDefinition.id)
    ).all()
    return {
        "id": category.id, "code": category.code,
        "name_bg": category.name_bg, "name_en": category.name_en,
        "name_ru": category.name_ru, "is_active": category.is_active,
        "capabilities": category.capabilities or [],
        "fields": [_category_field_dict(field) for field in fields],
    }


@legacy_router.get("/asset-categories/{category_id}/form-definition")
def asset_form_definition(
    category_id: int,
    user: User = Depends(require_asset_viewer), db: Session = Depends(get_db),
) -> dict:
    if is_observer(user):
        raise HTTPException(403, detail={"code": "asset_form_forbidden"})
    return _asset_form_category(db, category_id)


@legacy_router.get("/machines/{machine_id}/form-data")
def machine_form_data(
    machine_id: int,
    category_id: int | None = Query(default=None, ge=1),
    user: User = Depends(require_asset_viewer), db: Session = Depends(get_db),
) -> dict:
    if is_observer(user):
        raise HTTPException(403, detail={"code": "asset_form_forbidden"})
    machine = db.get(Machine, machine_id)
    if machine is None:
        raise HTTPException(404, "Машината не е намерена.")
    category = _asset_form_category(db, category_id or machine.category_id)
    ids = {field["id"] for field in category["fields"]}
    values = db.scalars(
        select(MachineFieldValue).where(MachineFieldValue.machine_id == machine_id)
    ).all()
    return {
        "category": category,
        "values": [{"field_id": item.field_id, "value": item.value} for item in values if item.field_id in ids],
    }


@legacy_router.get("/machines/{machine_id}", response_model=None)
def machine(
    machine_id: int,
    user: User = Depends(require_asset_viewer),
    db: Session = Depends(get_db),
) -> Machine | dict:
    return service.machine(machine_id=machine_id, user=user, db=db)


@legacy_router.post("/machines", response_model=MachineOut, status_code=201)
def create_machine(
    data: MachineCreate,
    user: User = Depends(require_permission(Permission.ASSETS_CREATE)),
    db: Session = Depends(get_db),
) -> Machine:
    return service.create_machine(data=data, user=user, db=db)


@legacy_router.patch("/machines/{machine_id}", response_model=MachineOut)
def update_machine(
    machine_id: int,
    data: MachineUpdate,
    user: User = Depends(require_permission(Permission.ASSETS_EDIT)),
    db: Session = Depends(get_db),
) -> Machine:
    return service.update_machine(machine_id=machine_id, data=data, user=user, db=db)


@legacy_router.get("/machines/{machine_id}/qr")
def qr(
    machine_id: int,
    request: Request,
    _: User = Depends(require_document_generator),
    db: Session = Depends(get_db),
) -> Response:
    return service.qr(machine_id=machine_id, request=request, _=_, db=db)


@router.get("/machines/{machine_id}/passport")
def machine_passport(
    machine_id: int,
    user: User = Depends(require_asset_viewer),
    db: Session = Depends(get_db),
) -> dict:
    return passport.machine_passport(machine_id=machine_id, user=user, db=db)


@router.get("/machines/{machine_id}/timeline", response_model=MachineTimelinePage)
def machine_timeline(
    machine_id: int,
    category: TimelineCategory = TimelineCategory.ALL,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    user: User = Depends(require_asset_viewer),
    db: Session = Depends(get_db),
) -> MachineTimelinePage:
    return timeline.machine_timeline(
        db, machine_id=machine_id, user=user, category=category, page=page, page_size=page_size
    )


@router.put("/machines/{machine_id}/custom-fields")
def update_custom_fields(
    machine_id: int,
    payload: CustomFieldValuesUpdate,
    user: User = Depends(require_permission(Permission.ASSETS_EDIT)),
    db: Session = Depends(get_db),
) -> dict:
    return custom_fields.update_custom_fields(
        machine_id=machine_id, payload=payload, user=user, db=db
    )


@router.post("/machines/{machine_id}/attachments", status_code=201)
def add_machine_attachment(
    machine_id: int,
    payload: AttachmentCreate,
    user: User = Depends(require_repair_operator),
    db: Session = Depends(get_db),
) -> dict:
    return attachments.add_machine_attachment(
        machine_id=machine_id, payload=payload, user=user, db=db
    )


@router.get("/machine-attachments/{attachment_id}/download")
def download_machine_attachment(
    attachment_id: int,
    _: User = Depends(require_document_viewer),
    db: Session = Depends(get_db),
) -> Response:
    return attachments.download_machine_attachment(attachment_id=attachment_id, _=_, db=db)
