"""Explicit owner deletion policy. History is fail-closed; ORM cascades are never used."""

from __future__ import annotations

from enum import Enum
from uuid import uuid4

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..auth_throttle import (
    clear_rate_limit_failures,
    enforce_rate_limit,
    record_rate_limit_failure,
    sensitive_rate_limit_keys,
    throttled_error,
)
from ..database import Base
from ..models import (
    AssetCategory,
    AuthSession,
    CatalogAssetBinding,
    CatalogDefinition,
    CatalogExtractionSession,
    CatalogRevision,
    CatalogRevisionArtifact,
    CatalogRevisionAssembly,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
    CatalogRevisionPositionHotspot,
    CatalogRevisionReferencePage,
    CatalogRevisionRepairKit,
    CatalogRevisionRepairKitComponent,
    CatalogRevisionVisualPage,
    CategoryFieldDefinition,
    Department,
    DocumentParticipant,
    ExternalSigner,
    InstallationOwnership,
    Location,
    Machine,
    MachineAttachment,
    MachineEvent,
    MachineFieldValue,
    OfficialDocument,
    OfficialDocumentVersion,
    SignatureSlot,
    User,
    UserRole,
)
from ..security import verify_password
from .audit_context import _correlation_id


class ResourceType(str, Enum):
    USER = "user"
    DEPARTMENT = "department"
    LOCATION = "location"
    ASSET_CATEGORY = "asset_category"
    CATEGORY_FIELD = "category_field"
    MACHINE = "machine"
    EXTERNAL_SIGNER = "external_signer"
    SIGNATURE_SLOT = "signature_slot"
    CATALOG_DEFINITION = "catalog_definition"


# There is no client-supplied table/model/SQL lookup.
RESOURCE_MODELS = {
    ResourceType.USER: User,
    ResourceType.DEPARTMENT: Department,
    ResourceType.LOCATION: Location,
    ResourceType.ASSET_CATEGORY: AssetCategory,
    ResourceType.CATEGORY_FIELD: CategoryFieldDefinition,
    ResourceType.MACHINE: Machine,
    ResourceType.EXTERNAL_SIGNER: ExternalSigner,
    ResourceType.SIGNATURE_SLOT: SignatureSlot,
    ResourceType.CATALOG_DEFINITION: CatalogDefinition,
}

# Every incoming FK is counted once per referencing row, including multiple
# actor/location columns. New FKs automatically block rather than being cascaded.
REFERENCE_LABELS = {
    "users": "users",
    "auth_sessions": "sessions",
    "machines": "machines",
    "repairs": "repairs",
    "transfer_batches": "transfers",
    "transfer_protocols": "transfers",
    "protocol_documents": "protocols",
    "part_requests": "partRequests",
    "part_catalog": "catalog",
    "part_catalog_images": "catalog",
    "technical_documents": "technicalDocuments",
    "category_field_definitions": "fields",
    "machine_field_values": "values",
    "machine_attachments": "attachments",
    "machine_events": "events",
    "repair_events": "repairs",
    "repair_participants": "repairs",
    "repair_parts": "repairs",
    "repair_attachments": "repairs",
    "document_template_versions": "templates",
    "generated_documents": "generatedDocuments",
    "part_request_lines": "partRequests",
    "part_request_approvals": "partRequests",
    "part_request_attachments": "partRequests",
    "part_hotspots": "catalog",
    "repair_kits": "repairKits",
    "catalog_position_hotspots": "catalog",
    "technical_document_revisions": "technicalDocuments",
    "audit_logs": "audit",
    "installation_ownership": "ownership",
    "emergency_access_sessions": "emergency",
    "software_licenses": "licenses",
    "external_signers": "signers",
    "official_documents": "officialDocuments",
    "official_document_versions": "officialDocuments",
    "document_participants": "participants",
    "signature_sessions": "signatures",
    "catalog_definitions": "builderCatalogs",
    "catalog_revisions": "builderRevisions",
    "catalog_asset_bindings": "builderBindings",
    "catalog_reference_associations": "catalog",
    "catalog_reference_parts": "catalog",
    "catalog_revision_reference_pages": "builderPages",
    "catalog_revision_assemblies": "builderAssemblies",
    "catalog_revision_artifacts": "builderArtifacts",
    "catalog_revision_visual_pages": "builderVisualPages",
    "catalog_revision_parts": "builderParts",
    "catalog_revision_part_page_maps": "builderPartPageMaps",
    "catalog_revision_position_hotspots": "builderHotspots",
    "catalog_revision_repair_kits": "builderRepairKits",
    "catalog_revision_repair_kit_components": "builderRepairKitComponents",
    "catalog_extraction_sessions": "builderReviewHistory",
    "catalog_extraction_sources": "builderReviewHistory",
    "catalog_extraction_attempts": "builderReviewHistory",
    "catalog_extraction_candidates": "builderReviewHistory",
    "catalog_source_review_decisions": "builderReviewHistory",
}

# Only local events are owned data. Unknown or operational events fail closed.
LOCAL_MACHINE_EVENTS = (
    "MACHINE_CREATED",
    "MACHINE_UPDATED",
    "CUSTOM_FIELDS_UPDATED",
    "ATTACHMENT_ADDED",
)
LOCAL_ATTACHMENT_KINDS = ("DOCUMENT", "PHOTO", "IMAGE")


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: SecretStr = Field(min_length=1, max_length=1024)
    confirmation_text: str = Field(min_length=1, max_length=1000)
    category_id: int | None = Field(default=None, gt=0)


def error(code: str, status: int = 409, **details) -> HTTPException:
    return HTTPException(status, detail={"code": code, **details})


def resource_type(value: str) -> ResourceType:
    try:
        return ResourceType(value)
    except ValueError as exc:
        raise error("unsupported_delete_resource", 422) from exc


def require_owner(db: Session, actor: User, *, lock: bool = False) -> User:
    """Read-only on preview, including an installation with no designation."""
    query = select(InstallationOwnership).order_by(InstallationOwnership.id)
    if lock:
        query = query.with_for_update()
    ownership = db.scalar(query.execution_options(populate_existing=True))
    authenticated_version = actor.token_version
    query = select(User).where(User.id == actor.id)
    if lock:
        query = query.with_for_update()
    current = db.scalar(query.execution_options(populate_existing=True))
    if (
        current is None
        or ownership is None
        or not current.is_active
        or not current.is_system_owner
        or current.role != UserRole.ADMINISTRATOR.value
        or current.id != ownership.owner_user_id
        or current.must_change_password
        or current.token_version != authenticated_version
    ):
        raise error("owner_only", 403)
    return current


def incoming_references(model):
    """Metadata is used only for fail-closed reads, never arbitrary deletion."""
    target = model.__table__.c.id
    for table in sorted(Base.metadata.tables.values(), key=lambda table: table.name):
        columns = [fk.parent for fk in table.foreign_keys if fk.column is target]
        if columns:
            yield table, columns


def _count(db: Session, table, predicate) -> int:
    return db.scalar(select(func.count()).select_from(table).where(predicate)) or 0


def _dependency(code: str, count: int, label: str | None = None) -> dict:
    return {
        "code": code,
        "count": count,
        "label_key": f"ownerDeletion.references.{label or REFERENCE_LABELS.get(code, 'related')}",
    }


def _resolve(db, kind, identifier, category_id=None, *, lock=False):
    model = RESOURCE_MODELS[kind]
    query = select(model).where(model.id == identifier)
    if lock:
        query = query.with_for_update()
    target = db.scalar(query.execution_options(populate_existing=True))
    if target is None:
        raise error("deletion_target_not_found", 404)
    if kind == ResourceType.CATEGORY_FIELD:
        if category_id is None:
            raise error("deletion_category_required", 422)
        if target.category_id != category_id:
            raise error("deletion_target_not_found", 404)
    return target


def _identity(kind, target) -> str:
    if kind == ResourceType.USER:
        return target.email
    if kind == ResourceType.MACHINE:
        return target.inventory_number
    if kind == ResourceType.CATEGORY_FIELD:
        return f"{target.category_id}/{target.code}"
    if kind == ResourceType.SIGNATURE_SLOT:
        return f"{target.document_type}/{target.code}"
    if kind == ResourceType.EXTERNAL_SIGNER:
        return f"{target.id}: {' '.join(filter(None, (target.first_name, target.middle_name, target.last_name)))}"
    return target.code if hasattr(target, "code") else target.name


def _analyze(db, actor, kind, target) -> dict:
    blockers, children = [], []
    owned = set()
    if kind == ResourceType.USER:
        owned = {AuthSession.__tablename__}
        ownership = db.scalar(select(InstallationOwnership))
        if (
            target.id == actor.id
            or target.is_system_owner
            or (ownership and target.id == ownership.owner_user_id)
        ):
            blockers.append(_dependency("system_owner_protected", 1, "owner"))
    elif kind == ResourceType.MACHINE:
        owned = {MachineFieldValue.__tablename__}
        for model, column, allowed in (
            (MachineEvent, MachineEvent.event_type, LOCAL_MACHINE_EVENTS),
            (MachineAttachment, MachineAttachment.kind, LOCAL_ATTACHMENT_KINDS),
        ):
            local = _count(db, model, (model.machine_id == target.id) & column.in_(allowed))
            protected = _count(db, model, (model.machine_id == target.id) & ~column.in_(allowed))
            if local:
                children.append(_dependency(model.__tablename__, local))
            if protected:
                blockers.append(_dependency(model.__tablename__, protected))
            owned.add(model.__tablename__)
    elif kind == ResourceType.ASSET_CATEGORY:
        owned = {CategoryFieldDefinition.__tablename__}
        fields = select(CategoryFieldDefinition.id).where(
            CategoryFieldDefinition.category_id == target.id
        )
        values = _count(db, MachineFieldValue, MachineFieldValue.field_id.in_(fields))
        if values:
            blockers.append(_dependency("machine_field_values", values))
        # Legacy category code is a current assignment too, not only the FK.
        count = _count(
            db,
            Machine,
            or_(
                Machine.category_id == target.id,
                Machine.category == target.code,
            ),
        )
        if count:
            blockers.append(_dependency("machines", count))
    elif kind == ResourceType.DEPARTMENT:
        aliases = {
            value.strip().casefold()
            for value in (
                target.code,
                target.name_bg,
                target.name_en,
                target.name_ru,
            )
            if value and value.strip()
        }
        # SQLite lower() does not case-fold Cyrillic. Count canonical codes and
        # legacy localized names identically on both supported database engines.
        count = sum(
            1
            for value in db.scalars(
                select(Machine.department).where(Machine.department.is_not(None))
            )
            if value.strip().casefold() in aliases
        )
        if count:
            blockers.append(_dependency("machines", count))
        versions = Base.metadata.tables["document_template_versions"]
        count = sum(
            1
            for value in db.scalars(
                select(versions.c.department).where(
                    versions.c.is_published.is_(True), versions.c.department.is_not(None)
                )
            )
            if value.strip().casefold() in aliases
        )
        if count:
            blockers.append(_dependency("document_template_versions", count))
    elif kind == ResourceType.SIGNATURE_SLOT:
        count = _count(
            db,
            DocumentParticipant,
            (DocumentParticipant.slot_code == target.code)
            & DocumentParticipant.document_version_id.in_(
                select(OfficialDocumentVersion.id)
                .join(OfficialDocument, OfficialDocument.id == OfficialDocumentVersion.document_id)
                .where(OfficialDocument.document_type == target.document_type)
            ),
        )
        if count:
            blockers.append(_dependency("document_participants", count))
        # Required slot configuration also affects pending documents without participants.
        count = _count(db, OfficialDocument, OfficialDocument.document_type == target.document_type)
        if count:
            blockers.append(_dependency("official_documents", count))
    elif kind == ResourceType.CATALOG_DEFINITION:
        owned = {CatalogRevision.__tablename__, CatalogAssetBinding.__tablename__,
                 CatalogRevisionReferencePage.__tablename__,
                 CatalogRevisionAssembly.__tablename__, CatalogRevisionArtifact.__tablename__,
                 CatalogRevisionVisualPage.__tablename__, CatalogRevisionPart.__tablename__,
                 CatalogRevisionPartPageMap.__tablename__, CatalogRevisionPositionHotspot.__tablename__,
                 CatalogRevisionRepairKit.__tablename__, CatalogRevisionRepairKitComponent.__tablename__}
        published = _count(db, CatalogRevision, (
            CatalogRevision.catalog_id == target.id
        ) & (CatalogRevision.status != "DRAFT"))
        if published:
            blockers.append(_dependency("catalog_revisions", published))
        revision_ids = select(CatalogRevision.id).where(CatalogRevision.catalog_id == target.id)
        review_history = _count(db, CatalogExtractionSession, CatalogExtractionSession.revision_id.in_(revision_ids))
        if review_history:
            blockers.append(_dependency("catalog_extraction_sessions", review_history))
        assembly_ids = select(CatalogRevisionAssembly.id).where(CatalogRevisionAssembly.revision_id.in_(revision_ids))
        artifact_ids = select(CatalogRevisionArtifact.id).where(CatalogRevisionArtifact.assembly_id.in_(assembly_ids))
        part_ids = select(CatalogRevisionPart.id).where(CatalogRevisionPart.assembly_id.in_(assembly_ids))
        page_ids = select(CatalogRevisionVisualPage.id).where(CatalogRevisionVisualPage.artifact_id.in_(artifact_ids))
        kit_ids = select(CatalogRevisionRepairKit.id).where(CatalogRevisionRepairKit.assembly_id.in_(assembly_ids))
        for model, condition in (
            (CatalogRevisionAssembly, CatalogRevisionAssembly.revision_id.in_(revision_ids)),
            (CatalogRevisionReferencePage, CatalogRevisionReferencePage.assembly_id.in_(assembly_ids)),
            (CatalogRevisionArtifact, CatalogRevisionArtifact.assembly_id.in_(assembly_ids)),
            (CatalogRevisionVisualPage, CatalogRevisionVisualPage.artifact_id.in_(artifact_ids)),
            (CatalogRevisionPart, CatalogRevisionPart.assembly_id.in_(assembly_ids)),
            (CatalogRevisionPartPageMap, CatalogRevisionPartPageMap.part_id.in_(part_ids)),
            (CatalogRevisionPositionHotspot, CatalogRevisionPositionHotspot.visual_page_id.in_(page_ids)),
            (CatalogRevisionRepairKit, CatalogRevisionRepairKit.assembly_id.in_(assembly_ids)),
            (CatalogRevisionRepairKitComponent, CatalogRevisionRepairKitComponent.kit_id.in_(kit_ids)),
        ):
            count = _count(db, model, condition)
            if count:
                children.append(_dependency(model.__tablename__, count))

    for table, columns in incoming_references(RESOURCE_MODELS[kind]):
        if kind == ResourceType.ASSET_CATEGORY and table.name == "machines":
            continue  # FK and legacy string already counted together above.
        count = _count(db, table, or_(*(column == target.id for column in columns)))
        if count and table.name not in {"machine_events", "machine_attachments"} & owned:
            (children if table.name in owned else blockers).append(_dependency(table.name, count))

    identity = _identity(kind, target)
    return {
        "resource_type": kind.value,
        "resource_id": target.id,
        "identity": identity,
        "can_delete": not blockers,
        "blockers": blockers,
        "owned_records_to_delete": children,
        "warnings": ["ownerDeletion.warning"],
        "confirmation_text": f"DELETE {identity}",
        "category_id": target.category_id if kind == ResourceType.CATEGORY_FIELD else None,
    }


def preview(
    db: Session, actor: User, kind: ResourceType, identifier: int, category_id=None
) -> dict:
    actor = require_owner(db, actor)
    target = _resolve(db, kind, identifier, category_id)
    return _analyze(db, actor, kind, target)


def _lock_dependencies(db: Session, kind: ResourceType) -> None:
    if db.get_bind().dialect.name != "postgresql":
        # Acquire SQLite's writer lock before dependency reads. SQLAlchemy has
        # opened a logical transaction, but sqlite hasn't begun a write one yet.
        db.execute(text("UPDATE installation_ownership SET version = version"))
        return
    tables = {table.name for table, _ in incoming_references(RESOURCE_MODELS[kind])}
    tables.add(RESOURCE_MODELS[kind].__tablename__)
    if kind in {ResourceType.DEPARTMENT, ResourceType.ASSET_CATEGORY}:
        tables.update(
            {
                "machines",
                "category_field_definitions",
                "machine_field_values",
                "document_template_versions",
            }
        )
    if kind == ResourceType.SIGNATURE_SLOT:
        tables.update({"document_participants", "official_documents", "official_document_versions"})
    if kind == ResourceType.CATALOG_DEFINITION:
        tables.update({"catalog_revisions", "catalog_asset_bindings", "catalog_revision_assemblies",
                       "catalog_revision_reference_pages",
                       "catalog_revision_artifacts", "catalog_revision_visual_pages",
                       "catalog_revision_parts", "catalog_revision_part_page_maps",
                       "catalog_revision_position_hotspots", "catalog_revision_repair_kits",
                       "catalog_revision_repair_kit_components", "catalog_extraction_sessions"})
    # Rare destructive operations serialize writers to their reference tables.
    # This covers string/configuration references and child-insert phantoms as
    # well as FKs, without requiring every existing writer to use a new service.
    preparer = db.get_bind().dialect.identifier_preparer
    names = ", ".join(preparer.quote(name) for name in sorted(tables))
    db.execute(text(f"LOCK TABLE {names} IN SHARE ROW EXCLUSIVE MODE"))


def _reject(db, actor, kind, identifier, code, correlation_id, **details):
    add_audit_log(
        db,
        actor,
        kind.value,
        identifier,
        "OWNER_PERMANENT_DELETE_REJECTED",
        {"resource_type": kind.value, "reason": code, **details},
        correlation_id,
    )
    db.commit()


def execute(
    db: Session,
    actor: User,
    kind: ResourceType,
    identifier: int,
    data: ExecuteRequest,
    request: Request,
) -> dict:
    correlation_id = _correlation_id(request) or str(uuid4())
    try:
        actor = require_owner(db, actor, lock=True)
        keys = sensitive_rate_limit_keys(request, actor, "owner_delete")
        enforce_rate_limit(db, keys)
        if not verify_password(data.current_password.get_secret_value(), actor.password_hash):
            retry = record_rate_limit_failure(
                db,
                keys,
                user=actor,
                action="OWNER_DELETE_REAUTHENTICATION_THROTTLED",
            )
            _reject(db, actor, kind, identifier, "reauthentication_failed", correlation_id)
            if retry:
                raise throttled_error(retry)
            raise error("reauthentication_failed", 403)
        if kind == ResourceType.CATALOG_DEFINITION:
            # Same order as Builder mutations: catalog row, then dependent data.
            # Taking table locks first could deadlock an in-flight review writer.
            from ..catalog_admin.visual_sources import lock_catalog
            lock_catalog(db, identifier)
        _lock_dependencies(db, kind)
        # SQLite ignores FOR UPDATE. Re-resolve authorization after its writer
        # lock too, closing an ownership/password change between initial reads
        # and the first write. PostgreSQL retains the designation/actor locks.
        actor = require_owner(db, actor, lock=True)
        target = _resolve(db, kind, identifier, data.category_id, lock=True)
        result = _analyze(db, actor, kind, target)
        if not result["can_delete"]:
            code = (
                "system_owner_protected"
                if any(item["code"] == "system_owner_protected" for item in result["blockers"])
                else "deletion_blocked"
            )
            _reject(db, actor, kind, identifier, code, correlation_id, blockers=result["blockers"])
            raise error(code, blockers=result["blockers"])
        if data.confirmation_text != result["confirmation_text"]:
            _reject(db, actor, kind, identifier, "deletion_confirmation_mismatch", correlation_id)
            raise error("deletion_confirmation_mismatch")
        clear_rate_limit_failures(db, keys)
        add_audit_log(
            db,
            actor,
            kind.value,
            identifier,
            "OWNER_PERMANENT_DELETE",
            {
                "resource_type": kind.value,
                "resource_id": identifier,
                "identity": result["identity"],
                "blockers": result["blockers"],
                "owned_records_to_delete": result["owned_records_to_delete"],
            },
            correlation_id,
        )
        db.flush()
        if kind == ResourceType.USER:
            db.execute(delete(AuthSession).where(AuthSession.user_id == identifier))
        elif kind == ResourceType.MACHINE:
            for model in (MachineFieldValue, MachineEvent, MachineAttachment):
                db.execute(delete(model).where(model.machine_id == identifier))
        elif kind == ResourceType.ASSET_CATEGORY:
            db.execute(
                delete(CategoryFieldDefinition).where(
                    CategoryFieldDefinition.category_id == identifier
                )
            )
        elif kind == ResourceType.CATALOG_DEFINITION:
            revision_ids = select(CatalogRevision.id).where(CatalogRevision.catalog_id == identifier)
            assembly_ids = select(CatalogRevisionAssembly.id).where(CatalogRevisionAssembly.revision_id.in_(revision_ids))
            artifact_ids = select(CatalogRevisionArtifact.id).where(CatalogRevisionArtifact.assembly_id.in_(assembly_ids))
            part_ids = select(CatalogRevisionPart.id).where(CatalogRevisionPart.assembly_id.in_(assembly_ids))
            page_ids = select(CatalogRevisionVisualPage.id).where(CatalogRevisionVisualPage.artifact_id.in_(artifact_ids))
            kit_ids = select(CatalogRevisionRepairKit.id).where(CatalogRevisionRepairKit.assembly_id.in_(assembly_ids))
            db.execute(delete(CatalogRevisionRepairKitComponent).where(
                CatalogRevisionRepairKitComponent.kit_id.in_(kit_ids)))
            db.execute(delete(CatalogRevisionRepairKit).where(CatalogRevisionRepairKit.assembly_id.in_(assembly_ids)))
            db.execute(delete(CatalogRevisionPositionHotspot).where(
                CatalogRevisionPositionHotspot.visual_page_id.in_(page_ids)))
            db.execute(delete(CatalogRevisionPartPageMap).where(CatalogRevisionPartPageMap.part_id.in_(part_ids)))
            db.execute(delete(CatalogRevisionPart).where(CatalogRevisionPart.assembly_id.in_(assembly_ids)))
            db.execute(delete(CatalogRevisionVisualPage).where(CatalogRevisionVisualPage.artifact_id.in_(artifact_ids)))
            db.execute(delete(CatalogRevisionArtifact).where(CatalogRevisionArtifact.assembly_id.in_(assembly_ids)))
            db.execute(delete(CatalogRevisionReferencePage).where(CatalogRevisionReferencePage.assembly_id.in_(assembly_ids)))
            db.execute(delete(CatalogRevisionAssembly).where(CatalogRevisionAssembly.revision_id.in_(revision_ids)))
            db.execute(delete(CatalogAssetBinding).where(CatalogAssetBinding.catalog_id == identifier))
            db.execute(delete(CatalogRevision).where(CatalogRevision.catalog_id == identifier))
        # Core deletion intentionally bypasses legacy ORM delete-orphan cascades
        # on Machine.repairs/transfers and CategoryFieldDefinition.values.
        db.execute(delete(RESOURCE_MODELS[kind]).where(RESOURCE_MODELS[kind].id == identifier))
        db.commit()
    except (IntegrityError, OperationalError) as exc:
        db.rollback()
        # Never return SQL, FK names, paths or bound parameters.
        raise error("deletion_conflict") from exc
    except HTTPException:
        db.rollback()
        raise
    return {
        "deleted": True,
        "resource_type": kind.value,
        "resource_id": identifier,
        "correlation_id": correlation_id,
    }
