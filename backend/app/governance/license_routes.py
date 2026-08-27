"""Original license HTTP contract; security dependencies remain on each endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..hardening_schemas import LicenseEnvelope, LicenseStatusOut
from ..models import User
from ..security import get_authenticated_user, get_current_active_user
from . import license_service as service

router = APIRouter()


@router.get("/license/validate", response_model=LicenseStatusOut)
@router.get("/license/status", response_model=LicenseStatusOut)
def license_status(
    _: User = Depends(get_authenticated_user), db: Session = Depends(get_db)
) -> dict:
    return service.license_status(_=_, db=db)


@router.post("/license/install", response_model=LicenseStatusOut)
def install_license(
    envelope: LicenseEnvelope,
    request: Request,
    actor: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.install_license(envelope=envelope, request=request, actor=actor, db=db)
