from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import math
from dataclasses import dataclass
from datetime import timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .models import AuditLog, AuthenticationThrottle, User, utcnow
from .settings import settings


@dataclass(frozen=True)
class RateLimitKey:
    scope: str
    key_hash: str
    attempts: int
    window_seconds: int
    base_block_seconds: int
    max_block_seconds: int


def _opaque_key(scope: str, value: str) -> str:
    payload = f"{scope}\0{value}".encode("utf-8")
    return hmac.new(settings.secret_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _trusted_proxy(remote: str) -> bool:
    try:
        address = ipaddress.ip_address(remote)
    except ValueError:
        return False
    for configured in (settings.trusted_proxy_ips or "").split(","):
        value = configured.strip()
        if not value:
            continue
        try:
            if address in ipaddress.ip_network(value, strict=False):
                return True
        except ValueError:
            continue
    return False


def remote_source(request: Request) -> str:
    direct = request.client.host if request.client else "unknown"
    if _trusted_proxy(direct):
        forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    try:
        return str(ipaddress.ip_address(direct))
    except ValueError:
        return "unknown"


def login_rate_limit_keys(request: Request, normalized_email: str) -> tuple[RateLimitKey, ...]:
    source = remote_source(request)
    common = {
        "window_seconds": settings.login_rate_limit_window_seconds,
        "base_block_seconds": settings.login_rate_limit_base_block_seconds,
        "max_block_seconds": settings.login_rate_limit_max_block_seconds,
    }
    return (
        RateLimitKey(
            "login_account",
            _opaque_key("login_account", normalized_email),
            settings.login_rate_limit_attempts,
            **common,
        ),
        RateLimitKey(
            "login_pair",
            _opaque_key("login_pair", f"{normalized_email}|{source}"),
            settings.login_rate_limit_attempts,
            **common,
        ),
        RateLimitKey(
            "login_source",
            _opaque_key("login_source", source),
            settings.login_source_rate_limit_attempts,
            **common,
        ),
    )


def sensitive_rate_limit_keys(
    request: Request,
    user: User,
    operation: str,
) -> tuple[RateLimitKey, ...]:
    source = remote_source(request)
    common = {
        "attempts": settings.sensitive_rate_limit_attempts,
        "window_seconds": settings.sensitive_rate_limit_window_seconds,
        "base_block_seconds": settings.sensitive_rate_limit_base_block_seconds,
        "max_block_seconds": settings.sensitive_rate_limit_max_block_seconds,
    }
    return (
        RateLimitKey(
            f"{operation}_account",
            _opaque_key(f"{operation}_account", str(user.id)),
            **common,
        ),
        RateLimitKey(
            f"{operation}_pair",
            _opaque_key(f"{operation}_pair", f"{user.id}|{source}"),
            **common,
        ),
    )


def _retry_after(row: AuthenticationThrottle) -> int:
    if row.blocked_until is None:
        return 0
    return max(0, math.ceil((row.blocked_until - utcnow()).total_seconds()))


def enforce_rate_limit(db: Session, keys: tuple[RateLimitKey, ...]) -> None:
    retry_after = 0
    for key in keys:
        row = db.scalar(
            select(AuthenticationThrottle).where(
                AuthenticationThrottle.scope == key.scope,
                AuthenticationThrottle.key_hash == key.key_hash,
            )
        )
        if row is not None:
            retry_after = max(retry_after, _retry_after(row))
    if retry_after:
        raise throttled_error(retry_after)


def throttled_error(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        headers={"Retry-After": str(retry_after)},
        detail={
            "code": "authentication_throttled",
            "message": "Твърде много неуспешни опити. Опитайте отново след кратко изчакване.",
            "retry_after_seconds": retry_after,
        },
    )


def _row_for_update(
    db: Session,
    key: RateLimitKey,
    *,
    now,
) -> AuthenticationThrottle:
    row = db.scalar(
        select(AuthenticationThrottle)
        .where(
            AuthenticationThrottle.scope == key.scope,
            AuthenticationThrottle.key_hash == key.key_hash,
        )
        .with_for_update()
    )
    if row is None:
        values = {
            "scope": key.scope,
            "key_hash": key.key_hash,
            "failure_count": 0,
            "window_started_at": now,
            "updated_at": now,
        }
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            statement = postgresql_insert(AuthenticationThrottle).values(**values)
            statement = statement.on_conflict_do_nothing(
                index_elements=["scope", "key_hash"]
            )
        elif dialect == "sqlite":
            statement = sqlite_insert(AuthenticationThrottle).values(**values)
            statement = statement.on_conflict_do_nothing(
                index_elements=["scope", "key_hash"]
            )
        else:
            raise RuntimeError(
                f"Unsupported authentication throttle database dialect: {dialect}"
            )
        db.execute(statement)
        row = db.scalar(
            select(AuthenticationThrottle)
            .where(
                AuthenticationThrottle.scope == key.scope,
                AuthenticationThrottle.key_hash == key.key_hash,
            )
            .with_for_update()
        )
        if row is None:
            raise RuntimeError("Authentication throttle row could not be created")
    return row


def record_rate_limit_failure(
    db: Session,
    keys: tuple[RateLimitKey, ...],
    *,
    user: User | None,
    action: str,
) -> int:
    now = utcnow()
    retry_after = 0
    activated_scopes: list[str] = []
    for key in keys:
        row = _row_for_update(db, key, now=now)
        if (now - row.window_started_at).total_seconds() >= key.window_seconds:
            row.failure_count = 0
            row.window_started_at = now
            row.blocked_until = None
        row.failure_count += 1
        row.updated_at = now
        if row.failure_count >= key.attempts:
            exponent = min(row.failure_count - key.attempts, 4)
            block_seconds = min(
                key.base_block_seconds * (2**exponent), key.max_block_seconds
            )
            row.blocked_until = now + timedelta(seconds=block_seconds)
            retry_after = max(retry_after, block_seconds)
            activated_scopes.append(key.scope)
    if activated_scopes:
        db.add(
            AuditLog(
                entity_type="authentication_security",
                entity_id=user.id if user else None,
                action=action,
                details=json.dumps(
                    {
                        "result": "throttled",
                        "scopes": sorted(activated_scopes),
                        "retry_after_seconds": retry_after,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                user_id=user.id if user else None,
                user_name=user.full_name if user else None,
            )
        )
    return retry_after


def clear_rate_limit_failures(db: Session, keys: tuple[RateLimitKey, ...]) -> None:
    pairs = {(key.scope, key.key_hash) for key in keys}
    if not pairs:
        return
    for scope, key_hash in pairs:
        db.execute(
            delete(AuthenticationThrottle).where(
                AuthenticationThrottle.scope == scope,
                AuthenticationThrottle.key_hash == key_hash,
            )
        )
