from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    """Naive UTC timestamp kept for compatibility with the existing schema."""
    return datetime.now(UTC).replace(tzinfo=None)


class MachineStatus(str, Enum):
    READY = "READY"
    ISSUED = "ISSUED"
    IN_USE = "IN_USE"
    RETURNED = "RETURNED"
    INSPECTION = "INSPECTION"
    CLEANING = "CLEANING"
    REPAIR = "REPAIR"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    WAITING_PARTS = "WAITING_PARTS"
    TESTING = "TESTING"


class TransferBatchStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PARTIALLY_RETURNED = "PARTIALLY_RETURNED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class TransferOperationStatus(str, Enum):
    AWAITING_SIGNATURE = "AWAITING_SIGNATURE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RepairStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    DIAGNOSIS = "DIAGNOSIS"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    WAITING_PARTS = "WAITING_PARTS"
    REPAIRING = "REPAIRING"
    TESTING = "TESTING"
    COMPLETED = "COMPLETED"


class PartRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ORDERED = "ORDERED"
    PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PartRequestPriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    URGENT = "URGENT"


class UserRole(str, Enum):
    ADMINISTRATOR = "administrator"
    DIRECTOR = "director"
    MECHANIC = "mechanic"
    OBSERVER = "observer"


class LanguageCode(str, Enum):
    BG = "bg"
    EN = "en"
    RU = "ru"


class ProfileStatus(str, Enum):
    INCOMPLETE = "PROFILE_INCOMPLETE"
    COMPLETE = "PROFILE_COMPLETE"


class LicenseType(str, Enum):
    TEST = "TEST"
    TRIAL = "TRIAL"
    ANNUAL = "ANNUAL"
    PERPETUAL = "PERPETUAL"
    SUPPORT_ONLY = "SUPPORT_ONLY"
    EMERGENCY_TEMPORARY = "EMERGENCY_TEMPORARY"


class OfficialDocumentStatus(str, Enum):
    DRAFT = "DRAFT"
    READY_FOR_SIGNATURE = "READY_FOR_SIGNATURE"
    PARTIALLY_SIGNED = "PARTIALLY_SIGNED"
    SIGNED = "SIGNED"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class FieldType(str, Enum):
    TEXT = "TEXT"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    DATE = "DATE"
    BOOLEAN = "BOOLEAN"
    SELECT = "SELECT"


class RepairEventType(str, Enum):
    ACCEPTED = "ACCEPTED"
    INSPECTION = "INSPECTION"
    CLEANING = "CLEANING"
    DIAGNOSIS = "DIAGNOSIS"
    APPROVAL = "APPROVAL"
    PARTS = "PARTS"
    REPAIR_ACTION = "REPAIR_ACTION"
    TEST = "TEST"
    STATUS_CHANGE = "STATUS_CHANGE"
    COMPLETED = "COMPLETED"
    NOTE = "NOTE"


class DocumentType(str, Enum):
    TRANSFER_ISSUE = "TRANSFER_ISSUE"
    TRANSFER_RETURN = "TRANSFER_RETURN"
    REPAIR_PROTOCOL = "REPAIR_PROTOCOL"
    PART_REQUEST = "PART_REQUEST"
    DAILY_REPORT = "DAILY_REPORT"
    QR_LABEL = "QR_LABEL"
    TECHNICAL = "TECHNICAL"


class ApprovalDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETURNED_FOR_CHANGES = "RETURNED_FOR_CHANGES"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('administrator', 'director', 'mechanic', 'observer')",
            name="ck_users_final_role",
        ),
        CheckConstraint(
            "NOT is_system_owner OR (role = 'administrator' AND is_active)",
            name="ck_users_owner_invariants",
        ),
        Index(
            "uq_users_single_system_owner",
            "is_system_owner",
            unique=True,
            sqlite_where=text("is_system_owner = 1"),
            postgresql_where=text("is_system_owner"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="Администратор")
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    middle_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id"), nullable=True, index=True
    )
    profile_status: Mapped[str] = mapped_column(
        String(30), default=ProfileStatus.INCOMPLETE.value,
        server_default=text("'PROFILE_INCOMPLETE'"), nullable=False
    )
    legal_name_exception: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    legal_name_exception_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    legal_name_exception_approved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    legal_name_exception_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(
        String(50), default=UserRole.OBSERVER.value,
        server_default=text("'observer'"), nullable=False
    )
    preferred_language: Mapped[str] = mapped_column(
        String(2), default=LanguageCode.BG.value, server_default=text("'bg'")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    is_system_owner: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    token_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    profile_department: Mapped["Department | None"] = relationship(
        foreign_keys=[department_id]
    )


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name_bg: Mapped[str] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name_ru: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Machine(Base):
    __tablename__ = "machines"

    id: Mapped[int] = mapped_column(primary_key=True)
    inventory_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(120), default="HPWJ")
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_categories.id"), nullable=True, index=True
    )
    brand: Mapped[str] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pressure_bar: Mapped[int] = mapped_column(Integer, default=500)
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(80), default=MachineStatus.READY.value)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    asset_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    subtype: Mapped[str | None] = mapped_column(String(120), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manufacture_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commissioning_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ownership: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    responsible_person: Mapped[str | None] = mapped_column(String(255), nullable=True)
    capacity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dimensions: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    location: Mapped[Location | None] = relationship()
    category_definition: Mapped[AssetCategory | None] = relationship()
    repairs: Mapped[list[Repair]] = relationship(
        back_populates="machine", cascade="all, delete-orphan"
    )
    transfers: Mapped[list[TransferProtocol]] = relationship(
        back_populates="machine", cascade="all, delete-orphan"
    )
    custom_values: Mapped[list[MachineFieldValue]] = relationship(
        back_populates="machine", cascade="all, delete-orphan"
    )
    attachments: Mapped[list[MachineAttachment]] = relationship(
        back_populates="machine", cascade="all, delete-orphan"
    )
    events: Mapped[list[MachineEvent]] = relationship(
        back_populates="machine", cascade="all, delete-orphan"
    )


class Repair(Base):
    __tablename__ = "repairs"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    reported_problem: Mapped[str] = mapped_column(Text)
    diagnosis: Mapped[str | None] = mapped_column(Text, nullable=True)
    work_performed: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    repair_reference: Mapped[str | None] = mapped_column(
        String(80), nullable=True, unique=True, index=True
    )
    repair_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(80), nullable=True)
    condition_before: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    reported_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    symptoms: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_work: Mapped[str | None] = mapped_column(Text, nullable=True)
    removed_parts_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleaning_required: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    cleaning_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    inspection_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    test_required: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    test_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    test_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_pressure_bar: Mapped[int | None] = mapped_column(Integer, nullable=True)
    leaks_detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    electrical_test_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    functional_test_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsible_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    accepted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    approved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    target_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        String(80), default=RepairStatus.ACCEPTED.value
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    machine: Mapped[Machine] = relationship(back_populates="repairs")
    responsible_user: Mapped[User | None] = relationship(
        foreign_keys=[responsible_user_id]
    )
    accepted_by: Mapped[User | None] = relationship(foreign_keys=[accepted_by_id])
    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_id])
    events: Mapped[list[RepairEvent]] = relationship(
        back_populates="repair", cascade="all, delete-orphan"
    )
    parts_used: Mapped[list[RepairPart]] = relationship(
        back_populates="repair", cascade="all, delete-orphan"
    )
    participants: Mapped[list[RepairParticipant]] = relationship(
        back_populates="repair", cascade="all, delete-orphan"
    )
    attachments: Mapped[list[RepairAttachment]] = relationship(
        back_populates="repair", cascade="all, delete-orphan"
    )
    generated_documents: Mapped[list[GeneratedDocument]] = relationship(
        back_populates="repair"
    )
    part_requests: Mapped[list[PartRequest]] = relationship(back_populates="repair")


class TransferBatch(Base):
    __tablename__ = "transfer_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_reference: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    status: Mapped[str] = mapped_column(
        String(80), default=TransferBatchStatus.ACTIVE.value
    )
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_manifest: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    issue_manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    issue_signing_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("official_documents.id"), nullable=True, unique=True, index=True
    )
    issue_signing_status: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    return_manifest: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    return_manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    return_signing_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("official_documents.id"), nullable=True, unique=True, index=True
    )
    return_signing_status: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)

    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])
    cancelled_by: Mapped[User | None] = relationship(foreign_keys=[cancelled_by_id])
    transfers: Mapped[list[TransferProtocol]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )
    documents: Mapped[list[ProtocolDocument]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class TransferProtocol(Base):
    __tablename__ = "transfer_protocols"
    __table_args__ = (
        Index(
            "uq_transfer_protocols_active_machine",
            "machine_id",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active IS TRUE"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("transfer_batches.id"), nullable=True, index=True
    )
    protocol_type: Mapped[str] = mapped_column(String(40), default="Предаване")
    protocol_number: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False, index=True
    )
    issue_status: Mapped[str] = mapped_column(
        String(40),
        default=TransferOperationStatus.COMPLETED.value,
        server_default=text("'COMPLETED'"),
        nullable=False,
        index=True,
    )
    return_status: Mapped[str | None] = mapped_column(
        String(40), nullable=True, index=True
    )
    company_unit: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vessel: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dock: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pier: Mapped[str | None] = mapped_column(String(120), nullable=True)
    work_area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    handed_over_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    handed_over_job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    handed_over_department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    accepted_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    accepted_by_job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    accepted_by_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    equipment: Mapped[str | None] = mapped_column(Text, nullable=True)
    hoses: Mapped[str | None] = mapped_column(Text, nullable=True)
    nozzles: Mapped[str | None] = mapped_column(Text, nullable=True)
    guns: Mapped[str | None] = mapped_column(Text, nullable=True)
    accessories: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_checklist: Mapped[list | None] = mapped_column(JSON, nullable=True)
    return_checklist: Mapped[list | None] = mapped_column(JSON, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    previous_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id"), nullable=True
    )
    issue_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id"), nullable=True
    )
    return_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id"), nullable=True
    )
    return_next_status: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    return_previous_status: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    return_previous_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id"), nullable=True
    )
    return_condition_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_missing_equipment: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_damage: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_contamination: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_cleaning_required: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    return_inspection_required: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    return_repair_required: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    returned_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    returned_by_job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    returned_by_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    return_accepted_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    return_accepted_job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    return_accepted_department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issued_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    returned_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    return_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    machine: Mapped[Machine] = relationship(back_populates="transfers")
    batch: Mapped[TransferBatch | None] = relationship(back_populates="transfers")
    issued_by: Mapped[User | None] = relationship(foreign_keys=[issued_by_id])
    returned_by_user: Mapped[User | None] = relationship(foreign_keys=[returned_by_id])
    documents: Mapped[list[ProtocolDocument]] = relationship(
        back_populates="transfer", cascade="all, delete-orphan"
    )

    @property
    def batch_reference(self) -> str | None:
        return self.batch.batch_reference if self.batch else None


class ProtocolDocument(Base):
    __tablename__ = "protocol_documents"
    __table_args__ = (
        UniqueConstraint("transfer_id", "format", name="uq_protocol_document_format"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_id: Mapped[int] = mapped_column(
        ForeignKey("transfer_protocols.id"), index=True
    )
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("transfer_batches.id"), index=True)
    format: Mapped[str] = mapped_column(String(8))
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(150))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    sha256: Mapped[str] = mapped_column(String(64))
    document_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    language: Mapped[str] = mapped_column(
        String(2), default=LanguageCode.BG.value, server_default=text("'bg'")
    )
    template_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_template_versions.id"), nullable=True, index=True
    )
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    transfer: Mapped[TransferProtocol] = relationship(back_populates="documents")
    machine: Mapped[Machine] = relationship()
    batch: Mapped[TransferBatch] = relationship(back_populates="documents")
    created_by: Mapped[User] = relationship()
    template_version: Mapped[DocumentTemplateVersion | None] = relationship()


class PartRequest(Base):
    __tablename__ = "part_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int | None] = mapped_column(
        ForeignKey("machines.id"), nullable=True
    )
    repair_id: Mapped[int | None] = mapped_column(
        ForeignKey("repairs.id"), nullable=True, index=True
    )
    repair_kit_id: Mapped[int | None] = mapped_column(
        ForeignKey("repair_kits.id"), nullable=True, index=True
    )
    repair_kit_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    part_name: Mapped[str] = mapped_column(String(255))
    part_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(
        String(50), default=PartRequestPriority.NORMAL.value
    )
    status: Mapped[str] = mapped_column(
        String(80), default=PartRequestStatus.DRAFT.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    request_reference: Mapped[str | None] = mapped_column(
        String(80), unique=True, nullable=True, index=True
    )
    language: Mapped[str] = mapped_column(
        String(2), default=LanguageCode.BG.value, server_default=text("'bg'")
    )
    requested_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    machine: Mapped[Machine | None] = relationship()
    repair: Mapped[Repair | None] = relationship(back_populates="part_requests")
    requested_by: Mapped[User | None] = relationship(
        foreign_keys=[requested_by_id]
    )
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id])
    lines: Mapped[list[PartRequestLine]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )
    approvals: Mapped[list[PartRequestApproval]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )
    attachments: Mapped[list[PartRequestAttachment]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )


class PartCatalog(Base):
    __tablename__ = "part_catalog"
    __table_args__ = (
        UniqueConstraint(
            "brand", "model", "assembly", "position", "part_number",
            name="uq_part_catalog_source_position",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str] = mapped_column(String(120), index=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    assembly: Mapped[str | None] = mapped_column(String(255), nullable=True)
    position: Mapped[str | None] = mapped_column(String(40), nullable=True)
    part_number: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_document: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_figure: Mapped[str | None] = mapped_column(String(255), nullable=True)
    diagram_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_document_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    verification_status: Mapped[str] = mapped_column(
        String(50), default="UNVERIFIED", server_default=text("'UNVERIFIED'"), nullable=False
    )
    replaced_by_part_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    name_bg: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name_ru: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    technical_specification: Mapped[str | None] = mapped_column(Text, nullable=True)
    compatible_models: Mapped[str | None] = mapped_column(Text, nullable=True)
    compatible_machine_numbers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    technical_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    supplier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    estimated_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    alternative_part_number: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    alternative_part_numbers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    replacement_part_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    verified_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    verified_by: Mapped[User | None] = relationship()
    hotspots: Mapped[list[PartHotspot]] = relationship(
        back_populates="part", cascade="all, delete-orphan"
    )
    images: Mapped[list[PartCatalogImage]] = relationship(
        back_populates="part", cascade="all, delete-orphan"
    )


class PartCatalogImage(Base):
    __tablename__ = "part_catalog_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("part_catalog.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(150))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    part: Mapped[PartCatalog] = relationship(back_populates="images")
    created_by: Mapped[User] = relationship()


class TechnicalDocument(Base):
    __tablename__ = "technical_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str] = mapped_column(String(120), index=True)
    category: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(500))
    file_path: Mapped[str] = mapped_column(String(700), unique=True)
    document_type: Mapped[str] = mapped_column(
        String(80), default=DocumentType.TECHNICAL.value,
        server_default=text("'TECHNICAL'"), nullable=False
    )
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    language: Mapped[str | None] = mapped_column(String(2), nullable=True)
    revision: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    document_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_machine_numbers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploaded_content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    uploaded_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    uploaded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    uploaded_by: Mapped[User | None] = relationship()
    revisions: Mapped[list[TechnicalDocumentRevision]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class AssetCategory(Base):
    __tablename__ = "asset_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name_bg: Mapped[str] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name_ru: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(120), nullable=True)
    validation_rules: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    document_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    checklists: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    fields: Mapped[list[CategoryFieldDefinition]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )


class CategoryFieldDefinition(Base):
    __tablename__ = "category_field_definitions"
    __table_args__ = (
        UniqueConstraint("category_id", "code", name="uq_category_field_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("asset_categories.id"), index=True
    )
    code: Mapped[str] = mapped_column(String(80))
    label_bg: Mapped[str] = mapped_column(String(255))
    label_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    label_ru: Mapped[str | None] = mapped_column(String(255), nullable=True)
    field_type: Mapped[str] = mapped_column(
        String(30), default=FieldType.TEXT.value, server_default=text("'TEXT'")
    )
    is_required: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    validation_rules: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )

    category: Mapped[AssetCategory] = relationship(back_populates="fields")
    values: Mapped[list[MachineFieldValue]] = relationship(
        back_populates="field", cascade="all, delete-orphan"
    )


class MachineFieldValue(Base):
    __tablename__ = "machine_field_values"
    __table_args__ = (
        UniqueConstraint("machine_id", "field_id", name="uq_machine_field_value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    field_id: Mapped[int] = mapped_column(
        ForeignKey("category_field_definitions.id"), index=True
    )
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    machine: Mapped[Machine] = relationship(back_populates="custom_values")
    field: Mapped[CategoryFieldDefinition] = relationship(back_populates="values")
    updated_by: Mapped[User | None] = relationship()


class MachineAttachment(Base):
    __tablename__ = "machine_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="DOCUMENT")
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(150))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    machine: Mapped[Machine] = relationship(back_populates="attachments")
    created_by: Mapped[User] = relationship()


class MachineEvent(Base):
    __tablename__ = "machine_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    previous_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    previous_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id"), nullable=True
    )
    new_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id"), nullable=True
    )
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    machine: Mapped[Machine] = relationship(back_populates="events")
    user: Mapped[User | None] = relationship()
    previous_location: Mapped[Location | None] = relationship(
        foreign_keys=[previous_location_id]
    )
    new_location: Mapped[Location | None] = relationship(
        foreign_keys=[new_location_id]
    )


class RepairEvent(Base):
    __tablename__ = "repair_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    repair_id: Mapped[int] = mapped_column(ForeignKey("repairs.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    status_before: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status_after: Mapped[str | None] = mapped_column(String(80), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    repair: Mapped[Repair] = relationship(back_populates="events")
    user: Mapped[User] = relationship()


class RepairParticipant(Base):
    __tablename__ = "repair_participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    repair_id: Mapped[int] = mapped_column(ForeignKey("repairs.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    full_name_snapshot: Mapped[str] = mapped_column(String(255))
    job_title_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    repair: Mapped[Repair] = relationship(back_populates="participants")
    user: Mapped[User | None] = relationship(foreign_keys=[user_id])
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])


class RepairPart(Base):
    __tablename__ = "repair_parts"

    id: Mapped[int] = mapped_column(primary_key=True)
    repair_id: Mapped[int] = mapped_column(ForeignKey("repairs.id"), index=True)
    catalog_part_id: Mapped[int | None] = mapped_column(
        ForeignKey("part_catalog.id"), nullable=True, index=True
    )
    part_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    repair: Mapped[Repair] = relationship(back_populates="parts_used")
    catalog_part: Mapped[PartCatalog | None] = relationship()
    created_by: Mapped[User] = relationship()


class RepairAttachment(Base):
    __tablename__ = "repair_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    repair_id: Mapped[int] = mapped_column(ForeignKey("repairs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(40), default="GENERAL")
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(150))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    repair: Mapped[Repair] = relationship(back_populates="attachments")
    created_by: Mapped[User] = relationship()


class DocumentTemplate(Base):
    __tablename__ = "document_templates"
    __table_args__ = (
        UniqueConstraint("document_type", "code", name="uq_document_template_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80))
    document_type: Mapped[str] = mapped_column(String(80), index=True)
    name_bg: Mapped[str] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name_ru: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    versions: Mapped[list[DocumentTemplateVersion]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class DocumentTemplateVersion(Base):
    __tablename__ = "document_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "template_id", "version", "language", name="uq_template_version_language"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("document_templates.id"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(2), default=LanguageCode.BG.value)
    source_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_media_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    source_content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    layout_contract: Mapped[dict] = mapped_column(JSON, default=dict)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    required_fields: Mapped[list | None] = mapped_column(JSON, nullable=True)
    numbering_rule: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_status: Mapped[str] = mapped_column(
        String(30), default="NOT_VALIDATED", server_default=text("'NOT_VALIDATED'"), nullable=False
    )
    validation_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    validated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    published_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    template: Mapped[DocumentTemplate] = relationship(back_populates="versions")
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])
    published_by: Mapped[User | None] = relationship(foreign_keys=[published_by_id])


class GeneratedDocument(Base):
    __tablename__ = "generated_documents"
    __table_args__ = (
        UniqueConstraint("document_number", "format", name="uq_generated_number_format"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_number: Mapped[str] = mapped_column(String(100), index=True)
    document_type: Mapped[str] = mapped_column(String(80), index=True)
    format: Mapped[str] = mapped_column(String(8))
    language: Mapped[str] = mapped_column(String(2), default=LanguageCode.BG.value)
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(150))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    sha256: Mapped[str] = mapped_column(String(64))
    template_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_template_versions.id"), nullable=True, index=True
    )
    machine_id: Mapped[int | None] = mapped_column(
        ForeignKey("machines.id"), nullable=True, index=True
    )
    repair_id: Mapped[int | None] = mapped_column(
        ForeignKey("repairs.id"), nullable=True, index=True
    )
    part_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("part_requests.id"), nullable=True, index=True
    )
    transfer_id: Mapped[int | None] = mapped_column(
        ForeignKey("transfer_protocols.id"), nullable=True, index=True
    )
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("transfer_batches.id"), nullable=True, index=True
    )
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    template_version: Mapped[DocumentTemplateVersion | None] = relationship()
    machine: Mapped[Machine | None] = relationship()
    repair: Mapped[Repair | None] = relationship(back_populates="generated_documents")
    part_request: Mapped[PartRequest | None] = relationship()
    transfer: Mapped[TransferProtocol | None] = relationship()
    batch: Mapped[TransferBatch | None] = relationship()
    created_by: Mapped[User] = relationship()


class PartRequestLine(Base):
    __tablename__ = "part_request_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("part_requests.id"), index=True)
    catalog_part_id: Mapped[int | None] = mapped_column(
        ForeignKey("part_catalog.id"), nullable=True, index=True
    )
    position: Mapped[str | None] = mapped_column(String(40), nullable=True)
    part_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document: Mapped[str | None] = mapped_column(String(700), nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivered_quantity: Mapped[float] = mapped_column(
        Float, default=0.0, server_default=text("0"), nullable=False
    )
    is_unknown_part: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False, index=True
    )
    assembly: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_catalog_part_id: Mapped[int | None] = mapped_column(
        ForeignKey("part_catalog.id"), nullable=True, index=True
    )
    linked_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    linked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    link_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    request: Mapped[PartRequest] = relationship(back_populates="lines")
    catalog_part: Mapped[PartCatalog | None] = relationship(
        foreign_keys=[catalog_part_id]
    )
    linked_catalog_part: Mapped[PartCatalog | None] = relationship(
        foreign_keys=[linked_catalog_part_id]
    )
    linked_by: Mapped[User | None] = relationship(foreign_keys=[linked_by_id])


class PartRequestApproval(Base):
    __tablename__ = "part_request_approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("part_requests.id"), index=True)
    decision: Mapped[str] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    request: Mapped[PartRequest] = relationship(back_populates="approvals")
    decided_by: Mapped[User] = relationship()


class PartRequestAttachment(Base):
    __tablename__ = "part_request_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("part_requests.id"), index=True)
    request_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("part_request_lines.id"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(150))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    request: Mapped[PartRequest] = relationship(back_populates="attachments")
    request_line: Mapped[PartRequestLine | None] = relationship()
    created_by: Mapped[User] = relationship()


class PartHotspot(Base):
    __tablename__ = "part_hotspots"

    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("part_catalog.id"), index=True)
    technical_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("technical_documents.id"), nullable=True, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    width: Mapped[float] = mapped_column(Float, default=0.03)
    height: Mapped[float] = mapped_column(Float, default=0.03)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provenance: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    part: Mapped[PartCatalog] = relationship(back_populates="hotspots")
    technical_document: Mapped[TechnicalDocument | None] = relationship()
    created_by: Mapped[User] = relationship()


class RepairKit(Base):
    __tablename__ = "repair_kits"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    compatible_models: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[str | None] = mapped_column(String(80), nullable=True)
    assembly: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_document: Mapped[str | None] = mapped_column(String(700), nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provenance: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_approved: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    approved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    components: Mapped[list[RepairKitComponent]] = relationship(
        back_populates="kit", cascade="all, delete-orphan"
    )
    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_id])
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])


class RepairKitComponent(Base):
    __tablename__ = "repair_kit_components"
    __table_args__ = (
        UniqueConstraint("kit_id", "part_id", name="uq_repair_kit_part"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kit_id: Mapped[int] = mapped_column(ForeignKey("repair_kits.id"), index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("part_catalog.id"), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    is_optional: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    kit: Mapped[RepairKit] = relationship(back_populates="components")
    part: Mapped[PartCatalog] = relationship()


class TechnicalDocumentRevision(Base):
    __tablename__ = "technical_document_revisions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_technical_document_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("technical_documents.id"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    revision_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(150))
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64))
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    document: Mapped[TechnicalDocument] = relationship(back_populates="revisions")
    created_by: Mapped[User | None] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(120))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operation_reference: Mapped[str | None] = mapped_column(
        String(80), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, index=True
    )

    user: Mapped[User | None] = relationship()


class InstallationOwnership(Base):
    """The protected owner designation is a property, never an RBAC role."""

    __tablename__ = "installation_ownership"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False, index=True
    )
    designated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    designated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    transfer_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))

    owner: Mapped[User] = relationship(foreign_keys=[owner_user_id])


class EmergencyAccessSession(Base):
    """Audited owner procedure; it never grants or expands RBAC permissions."""

    __tablename__ = "emergency_access_sessions"
    __table_args__ = (
        Index(
            "uq_emergency_access_active_owner",
            "owner_user_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
            sqlite_where=text("ended_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    reauthenticated_at: Mapped[datetime] = mapped_column(DateTime)
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    ended_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    end_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)


class SoftwareLicense(Base):
    __tablename__ = "software_licenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    license_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    signature: Mapped[str] = mapped_column(Text)
    license_type: Mapped[str] = mapped_column(String(40), index=True)
    client_name: Mapped[str] = mapped_column(String(255))
    installation_id: Mapped[str] = mapped_column(String(255), index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    grace_days: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    installed_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    installed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ExternalSigner(Base):
    __tablename__ = "external_signers"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(120))
    middle_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str] = mapped_column(String(120))
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    participant_role: Mapped[str] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_foreign_person: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    name_exception_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class OfficialDocument(Base):
    __tablename__ = "official_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_number: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    document_type: Mapped[str] = mapped_column(String(80), index=True)
    machine_id: Mapped[int | None] = mapped_column(ForeignKey("machines.id"), nullable=True, index=True)
    transfer_id: Mapped[int | None] = mapped_column(ForeignKey("transfer_protocols.id"), nullable=True, index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("transfer_batches.id"), nullable=True, index=True)
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OfficialDocumentVersion(Base):
    __tablename__ = "official_document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_official_document_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("official_documents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(40), default=OfficialDocumentStatus.DRAFT.value,
        server_default=text("'DRAFT'"), index=True
    )
    language: Mapped[str] = mapped_column(String(2), default=LanguageCode.BG.value)
    template_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_template_versions.id"), nullable=True, index=True
    )
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), index=True)
    signing_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    docx_content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    docx_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pdf_content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    pdf_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("official_document_versions.id"), nullable=True
    )
    prepared_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DocumentParticipant(Base):
    __tablename__ = "document_participants"
    __table_args__ = (
        UniqueConstraint("document_version_id", "slot_code", name="uq_document_participant_slot"),
        CheckConstraint(
            "(user_id IS NOT NULL AND external_signer_id IS NULL) OR "
            "(user_id IS NULL AND external_signer_id IS NOT NULL)",
            name="ck_document_participant_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_version_id: Mapped[int] = mapped_column(ForeignKey("official_document_versions.id"), index=True)
    slot_code: Mapped[str] = mapped_column(String(80))
    participant_kind: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    external_signer_id: Mapped[int | None] = mapped_column(ForeignKey("external_signers.id"), nullable=True, index=True)
    operation_role: Mapped[str] = mapped_column(String(120))
    identity_snapshot: Mapped[dict] = mapped_column(JSON)
    identity_snapshot_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SignatureSlot(Base):
    __tablename__ = "signature_slots"
    __table_args__ = (
        UniqueConstraint("document_type", "code", name="uq_signature_slot_type_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_type: Mapped[str] = mapped_column(String(80), index=True)
    code: Mapped[str] = mapped_column(String(80))
    label_bg: Mapped[str] = mapped_column(String(255))
    label_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    label_ru: Mapped[str | None] = mapped_column(String(255), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    allowed_participant_kind: Mapped[str] = mapped_column(String(20), default="ANY")
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    signing_mode: Mapped[str] = mapped_column(String(20), default="PARALLEL")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class SignatureSession(Base):
    __tablename__ = "signature_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("document_participants.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DocumentSignature(Base):
    __tablename__ = "document_signatures"
    __table_args__ = (
        UniqueConstraint("participant_id", name="uq_document_signature_participant"),
        Index(
            "uq_document_signatures_original_image_sha256",
            "image_sha256",
            unique=True,
            sqlite_where=text("image_sha256 IS NOT NULL AND source_signature_id IS NULL"),
            postgresql_where=text("image_sha256 IS NOT NULL AND source_signature_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("document_participants.id"), index=True)
    document_version_id: Mapped[int] = mapped_column(ForeignKey("official_document_versions.id"), index=True)
    signature_kind: Mapped[str] = mapped_column(String(40), default="MANUAL_GRAPHIC")
    consent_text: Mapped[str] = mapped_column(Text)
    strokes_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    image_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    canvas_width: Mapped[int] = mapped_column(Integer)
    canvas_height: Mapped[int] = mapped_column(Integer)
    stroke_count: Mapped[int] = mapped_column(Integer)
    point_count: Mapped[int] = mapped_column(Integer)
    document_sha256: Mapped[str] = mapped_column(String(64), index=True)
    image_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    signature_sha256: Mapped[str] = mapped_column(String(64), index=True)
    source_signature_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_signatures.id"), nullable=True, index=True
    )
    batch_manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    signed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
