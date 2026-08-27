"""Existing commit-time integrity-error translation shared by industrial domains."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .workflow import business_conflict


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise business_conflict(
            "database_integrity_conflict",
            "Операцията е в конфликт с вече съществуващ запис.",
        ) from exc
