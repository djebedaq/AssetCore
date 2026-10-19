"""Published template selection and preparer/signature display values."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..governance.profile_checks import _profile_complete
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
    from ..document_studio.publication import active_selection
    selected = active_selection(db, document_type, _language(language))
    if selected:
        version = db.get(DocumentTemplateVersion, selected.version_id)
        if (version is None or not version.is_published or version.validation_status != "PASSED"
                or not version.layout_contract.get("studio") or not version.template.is_active):
            raise ConfirmedTemplateUnavailableError(document_type, language)
        return version
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
            DocumentTemplateVersion.layout_contract["studio"].as_integer().is_(None),
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
    complete = _profile_complete(user) and user.profile_status == "PROFILE_COMPLETE"
    if not complete:
        raise TemplateValidationError(
            "Профилът на съставителя трябва да съдържа потвърдени име, фамилия и длъжност."
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
