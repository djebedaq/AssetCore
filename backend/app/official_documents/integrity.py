from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from ..models import OfficialDocument, OfficialDocumentStatus, OfficialDocumentVersion

CURRENT_VERSION_OWNER_CONSTRAINT = "fk_official_documents_current_version_owner"
CURRENT_VERSION_OWNER_INDEX = "uq_official_document_version_owner"
SQLITE_OWNER_TRIGGERS = frozenset(
    {
        "trg_official_documents_current_version_insert",
        "trg_official_documents_current_version_update",
        "trg_official_document_versions_current_owner_insert",
        "trg_official_document_versions_current_owner_update",
        "trg_official_document_versions_current_owner_delete",
    }
)

_CURRENT_COMPATIBLE_STATUSES = frozenset(
    status.value
    for status in OfficialDocumentStatus
    if status is not OfficialDocumentStatus.SUPERSEDED
)


@dataclass(frozen=True)
class OfficialDocumentIntegrityError(RuntimeError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def _identity_id(value: object, *, entity: str) -> int:
    identity = getattr(value, "id", None)
    if not isinstance(identity, int):
        raise OfficialDocumentIntegrityError(
            f"{entity}_not_persisted",
            f"{entity} трябва да бъде записан преди задаване на канонична версия.",
        )
    return identity


def require_version_for_document(
    db: Session,
    document: OfficialDocument,
    version_or_id: OfficialDocumentVersion | int | None,
    *,
    allowed_statuses: Collection[str] | None = None,
) -> OfficialDocumentVersion:
    document_id = _identity_id(document, entity="official_document")
    version_id = (
        version_or_id
        if isinstance(version_or_id, int) and not isinstance(version_or_id, bool)
        else getattr(version_or_id, "id", None)
    )
    if not isinstance(version_id, int):
        raise OfficialDocumentIntegrityError(
            "official_document_version_missing",
            "Каноничната версия на официалния документ не съществува.",
        )
    version = db.get(OfficialDocumentVersion, version_id)
    if version is None:
        raise OfficialDocumentIntegrityError(
            "official_document_version_missing",
            "Каноничната версия на официалния документ не съществува.",
        )
    if version.document_id != document_id:
        raise OfficialDocumentIntegrityError(
            "official_document_version_wrong_owner",
            "Каноничната версия принадлежи на друг официален документ.",
        )
    compatible = set(allowed_statuses or _CURRENT_COMPATIBLE_STATUSES)
    if version.status not in compatible:
        raise OfficialDocumentIntegrityError(
            "official_document_version_status_incompatible",
            "Статусът на версията не е допустим за канонична версия.",
        )
    return version


def require_current_version(
    db: Session,
    document: OfficialDocument,
    *,
    allowed_statuses: Collection[str] | None = None,
) -> OfficialDocumentVersion:
    return require_version_for_document(
        db,
        document,
        document.current_version_id,
        allowed_statuses=allowed_statuses,
    )


def set_current_version(
    db: Session,
    document: OfficialDocument,
    version_or_id: OfficialDocumentVersion | int,
    *,
    allowed_statuses: Collection[str] | None = None,
) -> OfficialDocumentVersion:
    version = require_version_for_document(
        db,
        document,
        version_or_id,
        allowed_statuses=allowed_statuses,
    )
    document.current_version_id = version.id
    return version


def move_current_version(
    db: Session,
    *,
    source_document: OfficialDocument,
    target_document: OfficialDocument,
    version: OfficialDocumentVersion,
) -> OfficialDocumentVersion:
    source_version = require_current_version(db, source_document)
    if source_version.id != version.id:
        raise OfficialDocumentIntegrityError(
            "official_document_source_version_mismatch",
            "Преместваната версия не е текущата версия на изходния документ.",
        )
    _identity_id(target_document, entity="official_document")
    source_document.current_version_id = None
    db.flush()
    version.document_id = target_document.id
    db.flush()
    return set_current_version(db, target_document, version)


def _finding(
    code: str,
    severity: str,
    rows: list[tuple[Any, ...]],
) -> dict[str, Any] | None:
    if not rows:
        return None
    return {
        "code": code,
        "severity": severity,
        "count": len(rows),
        "entity_ids": sorted(
            {
                int(row[0])
                for row in rows
                if row and isinstance(row[0], int)
            }
        ),
    }


def _schema_owner_guard(db: Session) -> tuple[bool, dict[str, Any]]:
    bind = db.get_bind()
    inspector = inspect(bind)
    foreign_keys = inspector.get_foreign_keys("official_documents")
    has_composite_fk = any(
        item.get("name") == CURRENT_VERSION_OWNER_CONSTRAINT
        and item.get("constrained_columns") == ["id", "current_version_id"]
        and item.get("referred_columns") == ["document_id", "id"]
        for item in foreign_keys
    )
    indexes = inspector.get_indexes("official_document_versions")
    has_owner_index = any(
        item.get("name") == CURRENT_VERSION_OWNER_INDEX
        and item.get("unique")
        and item.get("column_names") == ["document_id", "id"]
        for item in indexes
    )
    trigger_names: set[str] = set()
    if bind.dialect.name == "sqlite":
        trigger_names = set(
            db.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'trigger' AND name LIKE 'trg_official_document%'"
                )
            ).scalars()
        )
    has_sqlite_triggers = SQLITE_OWNER_TRIGGERS.issubset(trigger_names)
    has_postgresql_version_trigger = False
    if bind.dialect.name == "postgresql":
        has_postgresql_version_trigger = bool(
            db.execute(
                text(
                    "SELECT 1 FROM pg_trigger "
                    "WHERE tgname = 'trg_official_document_versions_current_owner' "
                    "AND NOT tgisinternal"
                )
            ).scalar()
        )
    protected = has_owner_index and (
        (has_composite_fk and bind.dialect.name != "postgresql")
        or (has_composite_fk and has_postgresql_version_trigger)
        or (bind.dialect.name == "sqlite" and has_sqlite_triggers)
    )
    return protected, {
        "dialect": bind.dialect.name,
        "composite_foreign_key": has_composite_fk,
        "owner_unique_index": has_owner_index,
        "sqlite_trigger_guard": has_sqlite_triggers,
        "postgresql_version_trigger_guard": has_postgresql_version_trigger,
    }


def validate_official_document_integrity(db: Session) -> dict[str, Any]:
    """Return a read-only integrity report without loading document/signature bytes."""

    protected, schema = _schema_owner_guard(db)
    findings: list[dict[str, Any]] = []
    if not protected:
        findings.append(
            {
                "code": "CURRENT_VERSION_OWNER_GUARD_MISSING",
                "severity": "BLOCKING",
                "count": 1,
                "entity_ids": [],
            }
        )

    null_current = list(
        db.execute(
            select(OfficialDocument.id).where(
                OfficialDocument.current_version_id.is_(None)
            )
        )
    )
    current_target = OfficialDocumentVersion.__table__.alias("current_target")
    missing_current = list(
        db.execute(
            select(OfficialDocument.id, OfficialDocument.current_version_id)
            .outerjoin(
                current_target,
                current_target.c.id == OfficialDocument.current_version_id,
            )
            .where(
                OfficialDocument.current_version_id.is_not(None),
                current_target.c.id.is_(None),
            )
        )
    )
    wrong_owner = list(
        db.execute(
            select(OfficialDocument.id, OfficialDocument.current_version_id)
            .join(
                current_target,
                current_target.c.id == OfficialDocument.current_version_id,
            )
            .where(current_target.c.document_id != OfficialDocument.id)
        )
    )
    owner_document = OfficialDocument.__table__.alias("owner_document")
    orphan_versions = list(
        db.execute(
            select(OfficialDocumentVersion.id, OfficialDocumentVersion.document_id)
            .outerjoin(
                owner_document,
                owner_document.c.id == OfficialDocumentVersion.document_id,
            )
            .where(owner_document.c.id.is_(None))
        )
    )
    shared_current = list(
        db.execute(
            select(
                OfficialDocument.current_version_id,
                func.count(OfficialDocument.id),
            )
            .where(OfficialDocument.current_version_id.is_not(None))
            .group_by(OfficialDocument.current_version_id)
            .having(func.count(OfficialDocument.id) > 1)
        )
    )
    duplicate_numbers = list(
        db.execute(
            select(func.min(OfficialDocument.id), func.count(OfficialDocument.id))
            .group_by(OfficialDocument.document_number)
            .having(func.count(OfficialDocument.id) > 1)
        )
    )
    duplicate_versions = list(
        db.execute(
            select(
                func.min(OfficialDocumentVersion.id),
                func.count(OfficialDocumentVersion.id),
            )
            .group_by(
                OfficialDocumentVersion.document_id,
                OfficialDocumentVersion.version,
            )
            .having(func.count(OfficialDocumentVersion.id) > 1)
        )
    )

    for finding in (
        _finding("CURRENT_VERSION_NULL", "TOLERATED_HISTORY", null_current),
        _finding("CURRENT_VERSION_TARGET_MISSING", "TOLERATED_HISTORY", missing_current),
        _finding("CURRENT_VERSION_WRONG_OWNER", "TOLERATED_HISTORY", wrong_owner),
        _finding("ORPHAN_DOCUMENT_VERSION", "TOLERATED_HISTORY", orphan_versions),
        _finding("CURRENT_VERSION_SHARED", "TOLERATED_HISTORY", shared_current),
        _finding("DUPLICATE_DOCUMENT_NUMBER", "BLOCKING", duplicate_numbers),
        _finding("DUPLICATE_DOCUMENT_VERSION", "BLOCKING", duplicate_versions),
    ):
        if finding is not None:
            findings.append(finding)

    blocking_count = sum(
        item["count"] for item in findings if item["severity"] == "BLOCKING"
    )
    tolerated_count = sum(
        item["count"]
        for item in findings
        if item["severity"] == "TOLERATED_HISTORY"
    )
    return {
        "valid": blocking_count == 0,
        "blocking_count": blocking_count,
        "tolerated_history_count": tolerated_count,
        "schema": schema,
        "findings": findings,
    }
