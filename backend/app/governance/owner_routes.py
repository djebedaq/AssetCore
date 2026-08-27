"""Original owner HTTP contract; security dependencies remain on each endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..hardening_schemas import OwnerStatusOut, OwnerTransferRequest
from ..models import User
from ..security import get_authenticated_user, get_current_active_user
from . import owner_service as service

router = APIRouter()
# Keep the existing registration order around the emergency routes.
transfer_router = APIRouter()


@router.get("/owner", response_model=OwnerStatusOut)
def owner_status(
    _: User = Depends(get_authenticated_user), db: Session = Depends(get_db)
) -> dict:
    return service.owner_status(_=_, db=db)


@router.get("/owner/audit")
def owner_audit_history(
    actor: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    return service.owner_audit_history(actor=actor, db=db)


@transfer_router.post("/owner/transfer", response_model=OwnerStatusOut)
def transfer_owner(
    data: OwnerTransferRequest,
    request: Request,
    actor: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.transfer_owner(data=data, request=request, actor=actor, db=db)
