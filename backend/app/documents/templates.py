"""Published template selection and preparer/signature display values."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import (
    DocumentTemplate,
    DocumentTemplateVersion,
    User,
)
from ..template_engine import TemplateValidationError
from .common import (
    ConfirmedTemplateUnavailableError,
    _language,
)


def _template_version(
    db: Session, document_type: str, language: str
) -> DocumentTemplateVersion:
    now = datetime.now(UTC).replace(tzinfo=None)
    version = db.scalar(
        select(DocumentTemplateVersion)
        .join(DocumentTemplate)
        .where(
            DocumentTemplate.document_type == document_type,
            DocumentTemplate.is_active.is_(True),
            DocumentTemplateVersion.language == _language(language),
            DocumentTemplateVersion.is_published.is_(True),
            DocumentTemplateVersion.validation_status == "PASSED",
            or_(
                DocumentTemplateVersion.effective_from.is_(None),
                DocumentTemplateVersion.effective_from <= now,
            ),
            or_(
                DocumentTemplateVersion.effective_to.is_(None),
                DocumentTemplateVersion.effective_to > now,
            ),
        )
        .order_by(DocumentTemplateVersion.version.desc())
    )
    if version is None:
        raise ConfirmedTemplateUnavailableError(document_type, language)
    return version


def _preparer_values(db: Session, created_by_id: int) -> dict[str, str]:
    user = db.get(User, created_by_id)
    if user is None:
        raise TemplateValidationError("Съставителят на документа не е намерен.")
    complete = bool(
        user.first_name
        and (
            user.middle_name
            or (
                user.legal_name_exception
                and user.legal_name_exception_reason
                and user.legal_name_exception_approved_by_id
                and user.legal_name_exception_approved_at
            )
        )
        and user.last_name
        and user.job_title
        and user.profile_status == "PROFILE_COMPLETE"
    )
    if not complete:
        raise TemplateValidationError(
            "Профилът на съставителя трябва да съдържа потвърдени три имена и длъжност."
        )
    return {"PREPARER_NAME": user.full_name, "PREPARER_JOB_TITLE": user.job_title}


def _signature_status(language: str, *, finalized_internal: bool = False) -> str:
    if finalized_internal:
        return {
            "bg": "ОКОНЧАТЕЛЕН ВЪТРЕШЕН ПРОТОКОЛ",
            "en": "FINAL INTERNAL PROTOCOL",
            "ru": "ОКОНЧАТЕЛЬНЫЙ ВНУТРЕННИЙ ПРОТОКОЛ",
        }[_language(language)]
    return {
        "bg": "НЕПЪЛНО ПОДПИСАН",
        "en": "NOT FULLY SIGNED",
        "ru": "ПОДПИСАН НЕ ПОЛНОСТЬЮ",
    }[_language(language)]
