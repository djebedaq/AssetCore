"""Authenticated HTTP adapters; explicit installation-owner checks live in service."""

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import get_current_active_user
from .owner_data_deletion import ExecuteRequest, execute, preview, resource_type

router = APIRouter(prefix="/owner/data-deletion")


@router.get("/{resource}/{resource_id}/preview")
def owner_deletion_preview(
    resource: str,
    resource_id: int = Path(gt=0),
    category_id: int | None = Query(None, gt=0),
    actor: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> dict:
    return preview(db, actor, resource_type(resource), resource_id, category_id)


@router.post("/{resource}/{resource_id}/execute")
def owner_deletion_execute(
    resource: str,
    data: ExecuteRequest,
    request: Request,
    resource_id: int = Path(gt=0),
    actor: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> dict:
    return execute(db, actor, resource_type(resource), resource_id, data, request)
