from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from .models import AuthenticationThrottle, AuthSession, User, utcnow
from .settings import settings

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cookie_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(minutes=settings.session_minutes)


def _set_session_cookies(
    response: Response,
    *,
    session_token: str,
    csrf_token: str,
) -> None:
    max_age = settings.session_minutes * 60
    expires = _cookie_expiry()
    common = {
        "max_age": max_age,
        "expires": expires,
        "path": "/",
        "secure": settings.browser_cookie_secure,
        "samesite": settings.session_cookie_samesite,
    }
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        httponly=True,
        **common,
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        httponly=False,
        **common,
    )


def clear_session_cookies(response: Response) -> None:
    for name in (settings.session_cookie_name, settings.csrf_cookie_name):
        response.delete_cookie(
            name,
            path="/",
            secure=settings.browser_cookie_secure,
            samesite=settings.session_cookie_samesite,
        )


def cleanup_auth_state(db: Session) -> None:
    cutoff = utcnow() - timedelta(days=settings.auth_state_retention_days)
    db.execute(
        delete(AuthSession).where(
            or_(
                AuthSession.expires_at < cutoff,
                AuthSession.revoked_at < cutoff,
            )
        )
    )
    db.execute(
        delete(AuthenticationThrottle).where(AuthenticationThrottle.updated_at < cutoff)
    )


def issue_browser_session(
    db: Session,
    user: User,
    request: Request,
    response: Response,
) -> AuthSession:
    existing_token = request.cookies.get(settings.session_cookie_name)
    if existing_token:
        existing = db.scalar(
            select(AuthSession).where(AuthSession.token_hash == secret_hash(existing_token))
        )
        if existing is not None and existing.revoked_at is None:
            existing.revoked_at = utcnow()
            existing.revoked_reason = "session_rotated"

    raw_session = secrets.token_urlsafe(48)
    raw_csrf = secrets.token_urlsafe(32)
    now = utcnow()
    session = AuthSession(
        user_id=user.id,
        token_hash=secret_hash(raw_session),
        csrf_token_hash=secret_hash(raw_csrf),
        user_token_version=user.token_version,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(minutes=settings.session_minutes),
    )
    db.add(session)
    db.flush()
    request.state.auth_method = "session"
    request.state.auth_session = session
    _set_session_cookies(
        response,
        session_token=raw_session,
        csrf_token=raw_csrf,
    )
    return session


def revoke_all_user_sessions(db: Session, user_id: int, reason: str) -> None:
    now = utcnow()
    for session in db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
    ):
        session.revoked_at = now
        session.revoked_reason = reason


def revoke_request_session(db: Session, request: Request, reason: str) -> None:
    session = getattr(request.state, "auth_session", None)
    if isinstance(session, AuthSession) and session.revoked_at is None:
        session.revoked_at = utcnow()
        session.revoked_reason = reason


def _invalid_session(language_message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "invalid_session", "message": language_message},
    )


def load_browser_session(
    request: Request,
    db: Session,
    *,
    invalid_message: str,
) -> User | None:
    raw_session = request.cookies.get(settings.session_cookie_name)
    if not raw_session:
        return None
    session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == secret_hash(raw_session))
    )
    now = utcnow()
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        raise _invalid_session(invalid_message)
    user = db.scalar(
        select(User).where(User.id == session.user_id, User.is_active.is_(True))
    )
    if user is None or session.user_token_version != user.token_version:
        session.revoked_at = now
        session.revoked_reason = "user_security_state_changed"
        db.commit()
        raise _invalid_session(invalid_message)
    if request.method.upper() in MUTATING_METHODS:
        supplied = request.headers.get("X-CSRF-Token", "")
        valid_csrf = bool(supplied) and len(supplied) <= 256 and hmac.compare_digest(
            secret_hash(supplied), session.csrf_token_hash
        )
        if not valid_csrf:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "csrf_failed",
                    "message": "Заявката е отхвърлена поради липсващ или невалиден CSRF код.",
                },
            )
    request.state.auth_method = "session"
    request.state.auth_session = session
    return user
