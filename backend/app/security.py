from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .localization import normalize_language, translate
from .models import User
from .settings import settings

bearer = HTTPBearer(auto_error=False)

OBVIOUSLY_WEAK_PASSWORDS = {
    "password",
    "password1",
    "password123",
    "qwerty123",
    "admin123",
    "changeme",
    "letmein123",
    "assetcore",
}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        _, rounds, salt, digest = hashed.split("$")
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), _unb64(salt), int(rounds)
        )
        return hmac.compare_digest(actual, _unb64(digest))
    except (ValueError, TypeError):
        return False


def validate_password_policy(password: str, email: str | None = None) -> None:
    normalized = password.casefold()
    email_value = (email or "").strip().casefold()
    email_local_part = email_value.split("@", 1)[0]
    valid = (
        len(password) >= 10
        and any(character.islower() for character in password)
        and any(character.isupper() for character in password)
        and any(character.isdigit() for character in password)
        and any(not character.isalnum() for character in password)
        and normalized not in OBVIOUSLY_WEAK_PASSWORDS
        and normalized != email_value
        and (not email_local_part or normalized != email_local_part)
    )
    if not valid:
        raise ValueError(
            "Паролата трябва да е поне 10 знака и да съдържа малка и главна "
            "буква, цифра и специален знак."
        )


def create_access_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "ver": user.token_version,
        "exp": int(time.time()) + settings.access_token_minutes * 60,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = _b64(
        hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).digest()
    )
    return f"{body}.{signature}"


def _decode(token: str, language: str = "bg") -> dict:
    try:
        body, signature = token.split(".", 1)
        expected = _b64(
            hmac.new(
                settings.secret_key.encode(), body.encode(), hashlib.sha256
            ).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        payload = json.loads(_unb64(body))
        if int(payload["exp"]) < int(time.time()):
            raise ValueError("expired token")
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=translate("auth.invalid_or_expired", language),
        ) from exc


def get_authenticated_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    language = normalize_language(request.headers.get("Accept-Language"))
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=translate("auth.required", language),
        )
    payload = _decode(credentials.credentials, language)
    try:
        user_id = int(payload["sub"])
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=translate("auth.invalid_session", language),
        ) from exc
    user = db.scalar(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=translate("auth.user_not_found", language),
        )
    if payload.get("ver") != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=translate("auth.invalid_session", language),
        )
    return user


def get_current_user(
    user: User = Depends(get_authenticated_user),
) -> User:
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "password_change_required",
                "message": "Трябва да смените временната си парола, преди да продължите.",
            },
        )
    return user


def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    return user
