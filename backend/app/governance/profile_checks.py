"""Existing complete-profile prerequisite shared by governance and document operations."""

from __future__ import annotations

from fastapi import HTTPException, status

from ..models import ProfileStatus, User


def _profile_complete(user: User) -> bool:
    has_middle = bool(user.middle_name) or (
        user.legal_name_exception
        and bool(user.legal_name_exception_reason)
        and bool(user.legal_name_exception_approved_by_id)
        and bool(user.legal_name_exception_approved_at)
    )
    return bool(user.first_name and has_middle and user.last_name and user.job_title)


def _require_complete_profile(user: User) -> None:
    if user.profile_status != ProfileStatus.COMPLETE.value or not _profile_complete(user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "profile_incomplete",
                "message": "Профилът трябва да съдържа потвърдени три имена и длъжност.",
            },
        )
