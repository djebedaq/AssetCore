"""Asset HTTP adapters retaining legacy schemas, route names and permissions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..industrial_schemas import AttachmentCreate, CustomFieldValuesUpdate
from ..models import Machine, User
from ..permissions import Permission, require_permission
from ..schemas import MachineCreate, MachineOut, MachineUpdate
from . import attachments, custom_fields, passport, service

legacy_router = APIRouter(prefix="/api")
router = APIRouter()
require_asset_viewer = require_permission(Permission.ASSETS_VIEW)
require_document_viewer = require_permission(Permission.DOCUMENTS_VIEW)
require_document_generator = require_permission(Permission.DOCUMENTS_GENERATE)
require_repair_operator = require_permission(Permission.REPAIRS_EDIT)


@legacy_router.get("/machines", response_model=None)
def machines(
    user: User = Depends(require_asset_viewer), db: Session = Depends(get_db)
) -> list[Machine] | list[dict]:
    return service.machines(user=user, db=db)


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
