"""Installation ownership operations; original checks, locks, audit and commits are preserved."""

from __future__ import annotations

import json

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..auth_sessions import revoke_all_user_sessions
from ..auth_throttle import (
    clear_rate_limit_failures,
    enforce_rate_limit,
    record_rate_limit_failure,
    sensitive_rate_limit_keys,
    throttled_error,
)
from ..hardening_schemas import OwnerTransferRequest
from ..models import AuditLog, InstallationOwnership, User, UserRole, utcnow
from ..security import verify_password
from .audit_context import _correlation_id
from .profile_checks import _require_complete_profile


def _ownership(db: Session, lock: bool = False) -> InstallationOwnership:
    query = select(InstallationOwnership).order_by(InstallationOwnership.id)
    if lock:
        query = query.with_for_update()
    item = db.scalar(query)
    if item is None:
        owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        if owner is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "owner_missing", "message": "Инсталацията няма определен собственик."},
            )
        item = InstallationOwnership(owner_user_id=owner.id, designated_by_id=owner.id)
        db.add(item)
        db.flush()
    return item


def owner_status(
    _: User, db: Session
) -> dict:
    item = _ownership(db)
    owner = db.get(User, item.owner_user_id)
    return {
        "owner_user_id": owner.id,
        "owner_name": owner.full_name,
        "owner_email": owner.email,
        "role": owner.role,
        "designated_at": item.designated_at,
        "designation_version": item.version,
    }


def owner_audit_history(
    actor: User,
    db: Session,
) -> list[dict]:
    ownership = _ownership(db)
    if actor.id != ownership.owner_user_id or actor.role != UserRole.ADMINISTRATOR.value:
        raise HTTPException(
            403,
            detail={
                "code": "owner_only",
                "message_key": "errors.ownerOnly",
                "message": "Историята на собствеността е достъпна само за определения собственик-администратор.",
            },
        )
    entries = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "installation_owner")
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    return [
        {
            "id": entry.id,
            "actor_user_id": entry.user_id,
            "actor_name": entry.user_name,
            "action": entry.action,
            "entity_id": entry.entity_id,
            "details": json.loads(entry.details) if entry.details else None,
            "correlation_id": entry.operation_reference,
            "created_at": entry.created_at,
        }
        for entry in entries
    ]


def transfer_owner(
    data: OwnerTransferRequest,
    request: Request,
    actor: User,
    db: Session,
) -> dict:
    _require_complete_profile(actor)
    item = _ownership(db, lock=True)
    if actor.id != item.owner_user_id or not actor.is_system_owner:
        raise HTTPException(403, detail={"code": "owner_only", "message": "Само текущият собственик може да прехвърли собствеността."})
    throttle_keys = sensitive_rate_limit_keys(request, actor, "owner_transfer")
    enforce_rate_limit(db, throttle_keys)
    if not verify_password(data.current_password, actor.password_hash):
        retry_after = record_rate_limit_failure(
            db,
            throttle_keys,
            user=actor,
            action="Ограничени неуспешни проверки за прехвърляне на собственост",
        )
        add_audit_log(db, actor, "installation_owner", actor.id, "Отказано прехвърляне на собственост", {"result": "rejected", "target_user_id": data.target_user_id, "reason": "invalid_reauthentication"}, _correlation_id(request))
        db.commit()
        if retry_after:
            raise throttled_error(retry_after)
        raise HTTPException(403, detail={"code": "reauthentication_failed", "message": "Текущата парола е неправилна."})
    clear_rate_limit_failures(db, throttle_keys)
    target = db.scalar(select(User).where(User.id == data.target_user_id).with_for_update())
    if target is None:
        raise HTTPException(404, detail={"code": "user_not_found", "message": "Новият собственик не е намерен."})
    if target.id == actor.id:
        raise HTTPException(409, detail={"code": "owner_unchanged", "message": "Избраният потребител вече е собственик."})
    if not target.is_active or target.role != UserRole.ADMINISTRATOR.value:
        raise HTTPException(409, detail={"code": "invalid_owner_target", "message": "Новият собственик трябва да е активен администратор."})
    _require_complete_profile(target)
    try:
        # Preserve the database-enforced single-owner invariant regardless of
        # SQLAlchemy's primary-key update ordering. The temporary zero-owner
        # state exists only inside this locked, uncommitted transaction.
        actor.is_system_owner = False
        db.flush()
        target.is_system_owner = True
        item.owner_user_id = target.id
        item.designated_by_id = actor.id
        item.designated_at = utcnow()
        item.transfer_reason = data.reason.strip()
        item.version += 1
        actor.token_version += 1
        target.token_version += 1
        revoke_all_user_sessions(db, actor.id, "owner_transferred")
        revoke_all_user_sessions(db, target.id, "owner_designated")
        add_audit_log(db, actor, "installation_owner", target.id, "Прехвърлена собственост на инсталацията", {"previous_owner_user_id": actor.id, "new_owner_user_id": target.id, "reason": data.reason.strip(), "designation_version": item.version}, _correlation_id(request))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, detail={"code": "owner_transfer_conflict", "message": "Собствеността е променена едновременно. Опитайте отново."}) from exc
    return owner_status(target, db)
