"""Signed-license installation and status; cryptographic policy remains in app.licensing."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..hardening_schemas import LicenseEnvelope
from ..licensing import (
    LicenseValidationError,
    active_license,
    evaluate_license,
    payload_hash,
    serialize_license_state,
    validate_envelope,
)
from ..models import Machine, SoftwareLicense, User, UserRole, utcnow
from .audit_context import _correlation_id
from .owner_service import _ownership
from .profile_checks import _require_complete_profile


def license_status(
    _: User, db: Session
) -> dict:
    return serialize_license_state(evaluate_license(db))


def install_license(
    envelope: LicenseEnvelope,
    request: Request,
    actor: User,
    db: Session,
) -> dict:
    _require_complete_profile(actor)
    ownership = _ownership(db, lock=True)
    if actor.id != ownership.owner_user_id or actor.role != UserRole.ADMINISTRATOR.value:
        raise HTTPException(403, detail={"code": "owner_only", "message": "Лицензът се управлява само от активния собственик-администратор."})
    try:
        payload = validate_envelope(envelope.payload, envelope.signature)
    except LicenseValidationError as exc:
        add_audit_log(db, actor, "software_license", None, "Отказано инсталиране на лиценз", {"result": "rejected", "reason": exc.code}, _correlation_id(request))
        db.commit()
        raise HTTPException(409, detail={"code": exc.code, "message": str(exc)}) from exc
    current_users = db.scalar(select(func.count(User.id))) or 0
    current_assets = db.scalar(select(func.count(Machine.id))) or 0
    if int(payload["max_users"]) < current_users or int(payload["max_assets"]) < current_assets:
        add_audit_log(
            db,
            actor,
            "software_license",
            None,
            "Отказано инсталиране на лиценз",
            {
                "result": "rejected",
                "reason": "license_capacity_below_current_usage",
                "current_users": current_users,
                "current_assets": current_assets,
            },
            _correlation_id(request),
        )
        db.commit()
        raise HTTPException(
            409,
            detail={
                "code": "license_capacity_below_current_usage",
                "message": "Лицензните ограничения са под текущия брой потребители или активи.",
                "current_users": current_users,
                "current_assets": current_assets,
            },
        )
    duplicate = db.scalar(select(SoftwareLicense).where(SoftwareLicense.license_id == str(payload["license_id"])))
    if duplicate is not None:
        raise HTTPException(409, detail={"code": "license_already_installed", "message": "Този лиценз вече е инсталиран."})
    previous = active_license(db)
    if previous:
        previous.is_active = False
        previous.superseded_at = utcnow()
    valid_from = _parse_license_date(payload.get("valid_from"))
    valid_until = _parse_license_date(payload.get("valid_until"))
    item = SoftwareLicense(
        license_id=str(payload["license_id"]), payload=payload,
        payload_sha256=payload_hash(payload), signature=envelope.signature,
        license_type=str(payload["license_type"]), client_name=str(payload["client_name"]),
        installation_id=str(payload["installation_id"]), valid_from=valid_from,
        valid_until=valid_until, grace_days=int(payload.get("grace_days", 0)),
        installed_by_id=actor.id,
    )
    db.add(item)
    db.flush()
    add_audit_log(db, actor, "software_license", item.id, "Инсталиран и проверен лиценз", {"license_id": item.license_id, "license_type": item.license_type, "payload_sha256": item.payload_sha256, "previous_license_id": previous.license_id if previous else None}, _correlation_id(request))
    db.commit()
    return serialize_license_state(evaluate_license(db))


def _parse_license_date(value: object):
    if value in (None, ""):
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=None) if parsed.tzinfo is None else parsed.astimezone(UTC).replace(tzinfo=None)
