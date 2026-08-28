from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import LicenseType, SoftwareLicense, utcnow
from .settings import settings

RIGHTSHOLDER = "Евтим Станиславов Горанов"
REQUIRED_FIELDS = {
    "license_id",
    "rightsholder",
    "client_name",
    "installation_id",
    "modules",
    "max_users",
    "max_assets",
    "valid_from",
    "license_type",
    "environment",
    "allowed_domains",
    "max_installations",
    "grace_days",
    "version",
}


class LicenseValidationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class LicenseState:
    state: str
    message: str
    read_only: bool
    license: SoftwareLicense | None = None
    grace_until: datetime | None = None
    verified_payload: dict | None = field(default=None, repr=False)


def canonical_payload(payload: dict) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _decode_public_key(value: str) -> Ed25519PublicKey:
    raw = value.strip().encode("ascii")
    if b"BEGIN PUBLIC KEY" in raw:
        key = serialization.load_pem_public_key(raw)
        if not isinstance(key, Ed25519PublicKey):
            raise LicenseValidationError("invalid_public_key", "Публичният ключ не е Ed25519.")
        return key
    try:
        decoded = base64.b64decode(raw, validate=True)
        return Ed25519PublicKey.from_public_bytes(decoded)
    except (ValueError, TypeError) as exc:
        raise LicenseValidationError(
            "invalid_public_key", "Публичният лицензионен ключ е невалиден."
        ) from exc


def validate_public_key_configuration(value: str | None) -> None:
    if not value:
        raise LicenseValidationError(
            "public_key_not_configured",
            "Публичният ключ за проверка на лиценз не е конфигуриран.",
        )
    _decode_public_key(value)


def _parse_datetime(value: object, field: str, required: bool = True) -> datetime | None:
    if value in (None, ""):
        if required:
            raise LicenseValidationError("invalid_license_payload", f"Липсва поле {field}.")
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo is None else parsed.astimezone(UTC).replace(tzinfo=None)
    except ValueError as exc:
        raise LicenseValidationError("invalid_license_payload", f"Полето {field} съдържа невалидна дата.") from exc


def validate_envelope(payload: dict, signature: str) -> dict:
    missing = sorted(REQUIRED_FIELDS - payload.keys())
    if missing:
        raise LicenseValidationError(
            "invalid_license_payload",
            f"Лицензът няма задължителни полета: {', '.join(missing)}.",
        )
    if payload.get("rightsholder") != RIGHTSHOLDER:
        raise LicenseValidationError(
            "rightsholder_mismatch", "Правоносителят в лиценза не съвпада с AssetCore."
        )
    try:
        license_type = LicenseType(str(payload["license_type"]))
    except ValueError as exc:
        raise LicenseValidationError("invalid_license_type", "Неподдържан тип лиценз.") from exc
    if not settings.license_public_key:
        raise LicenseValidationError(
            "public_key_not_configured",
            "Публичният ключ за проверка на лиценз не е конфигуриран.",
        )
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
        _decode_public_key(settings.license_public_key).verify(
            signature_bytes, canonical_payload(payload)
        )
    except (InvalidSignature, ValueError) as exc:
        raise LicenseValidationError(
            "invalid_license_signature", "Криптографският подпис на лиценза е невалиден."
        ) from exc
    expected_installation = settings.installation_id
    if expected_installation and payload["installation_id"] != expected_installation:
        raise LicenseValidationError(
            "installation_mismatch", "Лицензът е издаден за друга инсталация."
        )
    try:
        max_installations = int(payload.get("max_installations", 0))
        grace_days = int(payload.get("grace_days", 0))
        max_users = int(payload.get("max_users", 0))
        max_assets = int(payload.get("max_assets", 0))
        version = int(payload.get("version", 0))
    except (TypeError, ValueError) as exc:
        raise LicenseValidationError(
            "invalid_license_payload", "Числовите ограничения в лиценза са невалидни."
        ) from exc
    if max_installations < 1:
        raise LicenseValidationError("invalid_license_payload", "Броят инсталации трябва да е поне 1.")
    if grace_days < 0:
        raise LicenseValidationError("invalid_license_payload", "Гратисният период не може да е отрицателен.")
    if max_users < 1 or max_assets < 1 or version < 1:
        raise LicenseValidationError(
            "invalid_license_payload",
            "Лимитите за потребители и активи и версията трябва да са положителни числа.",
        )
    modules = payload.get("modules")
    if not isinstance(modules, list) or not modules or any(
        not isinstance(item, str) or not item.strip() for item in modules
    ):
        raise LicenseValidationError("invalid_license_payload", "Модулите трябва да са непразен списък от кодове.")
    domains = payload.get("allowed_domains")
    if not isinstance(domains, list) or any(
        not isinstance(item, str) or not item.strip() for item in domains
    ):
        raise LicenseValidationError("invalid_license_payload", "Разрешените домейни трябва да са списък.")
    environment = str(payload.get("environment", "")).strip().casefold()
    if environment not in {"development", "test", "staging", "production"}:
        raise LicenseValidationError("invalid_license_payload", "Средата в лиценза е невалидна.")
    if environment != settings.deployment_environment.casefold():
        raise LicenseValidationError(
            "environment_mismatch", "Лицензът е издаден за различна среда."
        )
    if settings.public_base_url and domains:
        current_host = (urlparse(settings.public_base_url).hostname or "").casefold()
        normalized_domains = {item.strip().casefold().lstrip(".") for item in domains}
        if current_host and not any(
            current_host == domain or current_host.endswith(f".{domain}")
            for domain in normalized_domains
        ):
            raise LicenseValidationError(
                "domain_mismatch", "Публичният домейн не е разрешен от лиценза."
            )
    valid_from = _parse_datetime(payload.get("valid_from"), "valid_from")
    _parse_datetime(payload.get("issued_at"), "issued_at", required=False)
    _parse_datetime(payload.get("activated_at"), "activated_at", required=False)
    _parse_datetime(payload.get("support_until"), "support_until", required=False)
    valid_until = _parse_datetime(
        payload.get("valid_until"),
        "valid_until",
        required=license_type not in {LicenseType.PERPETUAL, LicenseType.SUPPORT_ONLY},
    )
    if valid_from and valid_until and valid_until <= valid_from:
        raise LicenseValidationError(
            "invalid_license_payload", "Крайната дата на лиценза трябва да е след началната."
        )
    return payload


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(canonical_payload(payload)).hexdigest()


def _safe_optional_datetime(value: object, field: str) -> datetime | None:
    try:
        return _parse_datetime(value, field, required=False)
    except LicenseValidationError:
        return None


def active_license(db: Session) -> SoftwareLicense | None:
    return db.scalar(
        select(SoftwareLicense)
        .where(SoftwareLicense.is_active.is_(True))
        .order_by(SoftwareLicense.installed_at.desc(), SoftwareLicense.id.desc())
    )


def _entitlement_projections(payload: dict) -> dict:
    """Match installation normalization without changing the signed payload."""
    return {
        "license_id": str(payload["license_id"]),
        "client_name": str(payload["client_name"]),
        "license_type": str(payload["license_type"]),
        "installation_id": str(payload["installation_id"]),
        "valid_from": _parse_datetime(payload.get("valid_from"), "valid_from"),
        "valid_until": _parse_datetime(payload.get("valid_until"), "valid_until", required=False),
        "grace_days": int(payload["grace_days"]),
    }


def evaluate_license(db: Session, now: datetime | None = None) -> LicenseState:
    current = active_license(db)
    enforcement = settings.license_enforcement_enabled
    if current is None:
        return LicenseState(
            "NOT_INSTALLED",
            "Няма инсталиран лиценз.",
            enforcement,
        )
    try:
        payload = deepcopy(validate_envelope(current.payload, current.signature))
        if payload_hash(payload) != current.payload_sha256:
            raise LicenseValidationError(
                "license_payload_changed", "Съдържанието на лиценза е променено."
            )
        entitlement = _entitlement_projections(payload)
        if any(getattr(current, name) != value for name, value in entitlement.items()):
            raise LicenseValidationError(
                "license_projection_mismatch",
                "Съхранените лицензионни данни не съответстват на подписания лиценз.",
            )
    except LicenseValidationError:
        return LicenseState(
            "INVALID",
            "Криптографската проверка на инсталирания лиценз е неуспешна.",
            True,
            current,
        )
    now = now or utcnow()
    valid_from = entitlement["valid_from"]
    if valid_from and now < valid_from:
        return LicenseState(
            "NOT_YET_VALID", "Лицензът все още не е в сила.", True, current,
            verified_payload=payload,
        )
    valid_until = entitlement["valid_until"]
    if valid_until is None:
        return LicenseState("ACTIVE", "Лицензът е активен.", False, current, verified_payload=payload)
    grace_until = valid_until + timedelta(days=entitlement["grace_days"])
    if now <= valid_until:
        return LicenseState("ACTIVE", "Лицензът е активен.", False, current, grace_until, payload)
    if now <= grace_until:
        return LicenseState(
            "GRACE_PERIOD",
            "Лицензът е изтекъл и работи в гратисен период.",
            False,
            current,
            grace_until,
            payload,
        )
    return LicenseState(
        "READ_ONLY",
        "Лицензът и гратисният период са изтекли. Системата е само за четене.",
        True,
        current,
        grace_until,
        payload,
    )


def serialize_license_state(state: LicenseState) -> dict:
    # Never label mutable/unverified storage values as signed entitlement data.
    payload = state.verified_payload or {}
    entitlement = _entitlement_projections(payload) if payload else {}
    return {
        "state": state.state,
        "message": state.message,
        "read_only": state.read_only,
        "license_id": entitlement.get("license_id"),
        "license_type": entitlement.get("license_type"),
        "client_name": entitlement.get("client_name"),
        "rightsholder": payload.get("rightsholder"),
        "installation_id": entitlement.get("installation_id", settings.installation_id),
        "valid_from": entitlement.get("valid_from"),
        "valid_until": entitlement.get("valid_until"),
        "grace_until": state.grace_until,
        "issued_at": _safe_optional_datetime(payload.get("issued_at"), "issued_at"),
        "activated_at": _safe_optional_datetime(payload.get("activated_at"), "activated_at"),
        "support_until": _safe_optional_datetime(payload.get("support_until"), "support_until"),
        "checked_at": utcnow(),
        "modules": payload.get("modules", []),
        "max_users": payload.get("max_users"),
        "max_assets": payload.get("max_assets"),
        "environment": payload.get("environment"),
        "allowed_domains": payload.get("allowed_domains", []),
        "max_installations": payload.get("max_installations"),
        "version": payload.get("version"),
    }
