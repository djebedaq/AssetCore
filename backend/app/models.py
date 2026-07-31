from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
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
    ADMIN = "admin"
    MECHANIC = "mechanic"
    MANAGER = "manager"
    APPROVER = "approver"
    VIEWER = "viewer"


class LanguageCode(str, Enum):
    BG = "bg"
    EN = "en"
    RU = "ru"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="Администратор")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default=UserRole.ADMIN.value)
    preferred_language: Mapped[str] = mapped_column(
        String(2), default=LanguageCode.BG.value, server_default=text("'bg'")
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Machine(Base):
    __tablename__ = "machines"

    id: Mapped[int] = mapped_column(primary_key=True)
    inventory_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(120), default="HPWJ")
    brand: Mapped[str] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pressure_bar: Mapped[int] = mapped_column(Integer, default=500)
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(80), default=MachineStatus.READY.value)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    location: Mapped[Location | None] = relationship()
    repairs: Mapped[list[Repair]] = relationship(
        back_populates="machine", cascade="all, delete-orphan"
    )
    transfers: Mapped[list[TransferProtocol]] = relationship(
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
    status: Mapped[str] = mapped_column(
        String(80), default=RepairStatus.ACCEPTED.value
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    machine: Mapped[Machine] = relationship(back_populates="repairs")


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

    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])
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
    company_unit: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vessel: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    handed_over_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    accepted_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    equipment: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition_text: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    return_condition_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    returned_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    return_accepted_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issued_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    returned_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    transfer: Mapped[TransferProtocol] = relationship(back_populates="documents")
    machine: Mapped[Machine] = relationship()
    batch: Mapped[TransferBatch] = relationship(back_populates="documents")
    created_by: Mapped[User] = relationship()


class PartRequest(Base):
    __tablename__ = "part_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int | None] = mapped_column(
        ForeignKey("machines.id"), nullable=True
    )
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

    machine: Mapped[Machine | None] = relationship()


class PartCatalog(Base):
    __tablename__ = "part_catalog"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str] = mapped_column(String(120), index=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    assembly: Mapped[str | None] = mapped_column(String(255), nullable=True)
    position: Mapped[str | None] = mapped_column(String(40), nullable=True)
    part_number: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_document: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TechnicalDocument(Base):
    __tablename__ = "technical_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str] = mapped_column(String(120), index=True)
    category: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(500))
    file_path: Mapped[str] = mapped_column(String(700), unique=True)


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
