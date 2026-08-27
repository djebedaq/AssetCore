"""Original emergency HTTP contract; security dependencies remain on each endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..hardening_schemas import EmergencyAccessEnd, EmergencyAccessStart, EmergencyAccessStatusOut
from ..models import User
from ..security import get_current_active_user
from . import emergency_service as service

router = APIRouter()


@router.get("/emergency-access/status", response_model=EmergencyAccessStatusOut)
def emergency_access_status(
    _: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.emergency_access_status(_=_, db=db)


@router.post(
    "/emergency-access/start",
    response_model=EmergencyAccessStatusOut,
    status_code=status.HTTP_201_CREATED,
)
def start_emergency_access(
    data: EmergencyAccessStart,
    request: Request,
    actor: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.start_emergency_access(data=data, request=request, actor=actor, db=db)


@router.post(
    "/emergency-access/{session_id}/end",
    response_model=EmergencyAccessStatusOut,
)
def end_emergency_access(
    session_id: int,
    data: EmergencyAccessEnd,
    request: Request,
    actor: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.end_emergency_access(session_id=session_id, data=data, request=request, actor=actor, db=db)
