"""Bounded owner emergency context; this service never grants additional permissions."""

from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..auth_throttle import (
    clear_rate_limit_failures,
    enforce_rate_limit,
    record_rate_limit_failure,
    sensitive_rate_limit_keys,
    throttled_error,
)
from ..hardening_schemas import EmergencyAccessEnd, EmergencyAccessStart
from ..models import EmergencyAccessSession, User, UserRole, utcnow
from ..security import verify_password
from .audit_context import _correlation_id
from .owner_service import _ownership
from .profile_checks import _require_complete_profile


def _emergency_status(
    item: EmergencyAccessSession | None, db: Session
) -> dict:
    now = utcnow()
    active = bool(item and item.ended_at is None and item.expires_at > now)
    owner = db.get(User, item.owner_user_id) if active and item else None
    return {
        "active": active,
        "session_id": item.id if active and item else None,
        "started_at": item.started_at if active and item else None,
        "expires_at": item.expires_at if active and item else None,
        "owner_name": owner.full_name if owner else None,
        "mfa_verified": bool(item and item.mfa_verified_at) if active else False,
        "message": (
            "Активна е контролирана аварийна административна процедура. "
            "Тя не разширява системните права и приключва автоматично в посочения час."
            if active
            else "Няма активна аварийна административна процедура."
        ),
    }


def emergency_access_status(
    _: User,
    db: Session,
) -> dict:
    item = db.scalar(
        select(EmergencyAccessSession)
        .where(
            EmergencyAccessSession.ended_at.is_(None),
            EmergencyAccessSession.expires_at > utcnow(),
        )
        .order_by(EmergencyAccessSession.started_at.desc())
    )
    return _emergency_status(item, db)


def start_emergency_access(
    data: EmergencyAccessStart,
    request: Request,
    actor: User,
    db: Session,
) -> dict:
    _require_complete_profile(actor)
    ownership = _ownership(db, lock=True)
    if (
        actor.id != ownership.owner_user_id
        or actor.role != UserRole.ADMINISTRATOR.value
        or not actor.is_system_owner
    ):
        raise HTTPException(
            403,
            detail={
                "code": "owner_only",
                "message_key": "errors.ownerOnly",
                "message": "Аварийна процедура може да започне само определеният собственик-администратор.",
            },
        )
    throttle_keys = sensitive_rate_limit_keys(request, actor, "emergency_start")
    enforce_rate_limit(db, throttle_keys)
    if not verify_password(data.current_password, actor.password_hash):
        retry_after = record_rate_limit_failure(
            db,
            throttle_keys,
            user=actor,
            action="Ограничени неуспешни проверки за начало на аварийна процедура",
        )
        add_audit_log(
            db,
            actor,
            "emergency_access",
            None,
            "Отказано начало на аварийна административна процедура",
            {"result": "rejected", "reason": "invalid_reauthentication"},
            _correlation_id(request),
        )
        db.commit()
        if retry_after:
            raise throttled_error(retry_after)
        raise HTTPException(
            403,
            detail={
                "code": "reauthentication_failed",
                "message_key": "errors.reauthenticationFailed",
                "message": "Текущата парола е неправилна.",
            },
        )
    clear_rate_limit_failures(db, throttle_keys)

    now = utcnow()
    expired_items = db.scalars(
        select(EmergencyAccessSession)
        .where(
            EmergencyAccessSession.owner_user_id == actor.id,
            EmergencyAccessSession.ended_at.is_(None),
            EmergencyAccessSession.expires_at <= now,
        )
        .with_for_update()
    ).all()
    for expired in expired_items:
        expired.ended_at = expired.expires_at
        expired.end_reason = "Автоматично приключване след изтичане на определения срок."

    existing = db.scalar(
        select(EmergencyAccessSession)
        .where(
            EmergencyAccessSession.ended_at.is_(None),
            EmergencyAccessSession.expires_at > now,
        )
        .with_for_update()
    )
    if existing:
        add_audit_log(
            db,
            actor,
            "emergency_access",
            existing.id,
            "Отказано повторно начало на аварийна административна процедура",
            {"result": "rejected", "reason": "already_active"},
            _correlation_id(request),
        )
        db.commit()
        raise HTTPException(
            409,
            detail={
                "code": "emergency_access_already_active",
                "message": "Вече има активна аварийна административна процедура.",
            },
        )

    item = EmergencyAccessSession(
        owner_user_id=actor.id,
        reason=data.reason.strip(),
        started_at=now,
        expires_at=now + timedelta(minutes=data.duration_minutes),
        reauthenticated_at=now,
        correlation_id=_correlation_id(request),
    )
    db.add(item)
    db.flush()
    add_audit_log(
        db,
        actor,
        "emergency_access",
        item.id,
        "Започната контролирана аварийна административна процедура",
        {
            "reason": item.reason,
            "started_at": item.started_at.isoformat(),
            "expires_at": item.expires_at.isoformat(),
            "mfa_verified": False,
            "permissions_elevated": False,
        },
        item.correlation_id,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "emergency_access_conflict",
                "message": "Аварийната процедура е променена едновременно. Опитайте отново.",
            },
        ) from exc
    db.refresh(item)
    return _emergency_status(item, db)


def end_emergency_access(
    session_id: int,
    data: EmergencyAccessEnd,
    request: Request,
    actor: User,
    db: Session,
) -> dict:
    _require_complete_profile(actor)
    ownership = _ownership(db, lock=True)
    if actor.id != ownership.owner_user_id or actor.role != UserRole.ADMINISTRATOR.value:
        raise HTTPException(403, detail={"code": "owner_only", "message": "Само текущият собственик може да приключи аварийната процедура."})
    throttle_keys = sensitive_rate_limit_keys(request, actor, "emergency_end")
    enforce_rate_limit(db, throttle_keys)
    if not verify_password(data.current_password, actor.password_hash):
        retry_after = record_rate_limit_failure(
            db,
            throttle_keys,
            user=actor,
            action="Ограничени неуспешни проверки за край на аварийна процедура",
        )
        add_audit_log(db, actor, "emergency_access", session_id, "Отказано приключване на аварийна административна процедура", {"result": "rejected", "reason": "invalid_reauthentication"}, _correlation_id(request))
        db.commit()
        if retry_after:
            raise throttled_error(retry_after)
        raise HTTPException(403, detail={"code": "reauthentication_failed", "message": "Текущата парола е неправилна."})
    clear_rate_limit_failures(db, throttle_keys)
    item = db.scalar(
        select(EmergencyAccessSession)
        .where(EmergencyAccessSession.id == session_id)
        .with_for_update()
    )
    if item is None:
        raise HTTPException(404, detail={"code": "emergency_access_not_found", "message": "Аварийната процедура не е намерена."})
    if item.owner_user_id != actor.id:
        raise HTTPException(403, detail={"code": "owner_only", "message": "Процедурата принадлежи на друг определен собственик."})
    if item.ended_at is not None or item.expires_at <= utcnow():
        raise HTTPException(409, detail={"code": "emergency_access_not_active", "message": "Аварийната процедура вече не е активна."})
    item.ended_at = utcnow()
    item.ended_by_id = actor.id
    item.end_reason = data.reason.strip()
    add_audit_log(db, actor, "emergency_access", item.id, "Приключена аварийна административна процедура", {"reason": item.end_reason, "ended_at": item.ended_at.isoformat(), "permissions_elevated": False}, _correlation_id(request))
    db.commit()
    return _emergency_status(item, db)
