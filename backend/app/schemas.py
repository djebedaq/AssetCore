from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .localization import (
    LEGACY_MACHINE_STATUS_CODES,
    LEGACY_PART_REQUEST_PRIORITY_CODES,
    LEGACY_PART_REQUEST_STATUS_CODES,
    LEGACY_REPAIR_STATUS_CODES,
)
from .models import (
    LanguageCode,
    MachineStatus,
    PartRequestPriority,
    PartRequestStatus,
    RepairStatus,
    TransferBatchStatus,
    UserRole,
)
from .security import validate_password_policy


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: str
    preferred_language: LanguageCode
    is_active: bool
    is_system_owner: bool
    must_change_password: bool
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None
    password_changed_at: datetime | None = None


def _normalize_email(value: str) -> str:
    normalized = value.strip().casefold()
    if (
        not normalized
        or "@" not in normalized
        or normalized.startswith("@")
        or normalized.endswith("@")
        or "." not in normalized.rsplit("@", 1)[1]
        or len(normalized) > 255
    ):
        raise ValueError("Въведете валиден служебен имейл адрес.")
    return normalized


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    full_name: str = Field(min_length=2, max_length=255)
    role: UserRole
    preferred_language: LanguageCode = LanguageCode.BG
    temporary_password: str
    confirm_password: str
    is_active: bool = True

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)

    @model_validator(mode="after")
    def validate_account(self):
        if self.temporary_password != self.confirm_password:
            raise ValueError("Паролите не съвпадат.")
        validate_password_policy(self.temporary_password, self.email)
        self.full_name = self.full_name.strip()
        if len(self.full_name) < 2:
            raise ValueError("Името трябва да съдържа поне два знака.")
        return self


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    role: UserRole | None = None
    preferred_language: LanguageCode | None = None
    is_active: bool | None = None

    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Името трябва да съдържа поне два знака.")
        return normalized


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temporary_password: str
    confirm_password: str

    @model_validator(mode="after")
    def passwords_match(self):
        if self.temporary_password != self.confirm_password:
            raise ValueError("Паролите не съвпадат.")
        return self


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: str
    confirm_password: str

    @model_validator(mode="after")
    def passwords_match(self):
        if self.new_password != self.confirm_password:
            raise ValueError("Паролите не съвпадат.")
        return self


class UserActionResponse(BaseModel):
    message: str
    user: UserOut


class LanguagePreferenceUpdate(BaseModel):
    preferred_language: LanguageCode


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    is_active: bool = True


class MachineBase(BaseModel):
    inventory_number: str
    name: str
    category: str = "HPWJ"
    category_id: int | None = None
    brand: str
    model: str | None = None
    pressure_bar: int = 500
    serial_number: str | None = None
    status: MachineStatus = MachineStatus.READY
    location_id: int | None = None
    notes: str | None = None
    asset_type: str | None = None
    subtype: str | None = None
    manufacturer: str | None = None
    manufacture_year: int | None = Field(default=None, ge=1800, le=2200)
    commissioning_date: datetime | None = None
    ownership: str | None = None
    department: str | None = None
    responsible_person: str | None = None
    capacity: str | None = None
    dimensions: str | None = None
    is_active: bool = True

    @field_validator("status", mode="before")
    @classmethod
    def accept_legacy_status(cls, value):
        return LEGACY_MACHINE_STATUS_CODES.get(value, value)


class MachineCreate(MachineBase):
    pass


class MachineUpdate(BaseModel):
    category_id: int | None = None
    name: str | None = None
    brand: str | None = None
    model: str | None = None
    pressure_bar: int | None = None
    serial_number: str | None = None
    status: MachineStatus | None = None
    location_id: int | None = None
    notes: str | None = None
    asset_type: str | None = None
    subtype: str | None = None
    manufacturer: str | None = None
    manufacture_year: int | None = Field(default=None, ge=1800, le=2200)
    commissioning_date: datetime | None = None
    ownership: str | None = None
    department: str | None = None
    responsible_person: str | None = None
    capacity: str | None = None
    dimensions: str | None = None
    is_active: bool | None = None

    @field_validator("status", mode="before")
    @classmethod
    def accept_legacy_status(cls, value):
        return LEGACY_MACHINE_STATUS_CODES.get(value, value)


class MachineOut(MachineBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: MachineStatus | str
    location: LocationOut | None = None
    created_at: datetime
    updated_at: datetime


class RepairCreate(BaseModel):
    machine_id: int
    reported_problem: str
    diagnosis: str | None = None
    work_performed: str | None = None
    result: str | None = None
    status: RepairStatus = RepairStatus.ACCEPTED

    @field_validator("status", mode="before")
    @classmethod
    def accept_legacy_status(cls, value):
        return LEGACY_REPAIR_STATUS_CODES.get(value, value)


class RepairUpdate(BaseModel):
    diagnosis: str | None = None
    work_performed: str | None = None
    result: str | None = None
    status: RepairStatus | None = None
    close: bool = False

    @field_validator("status", mode="before")
    @classmethod
    def accept_legacy_status(cls, value):
        return LEGACY_REPAIR_STATUS_CODES.get(value, value)


class RepairOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    machine: MachineOut
    reported_problem: str
    diagnosis: str | None = None
    work_performed: str | None = None
    result: str | None = None
    status: str
    opened_at: datetime
    closed_at: datetime | None = None


class PartRequestCreate(BaseModel):
    machine_id: int | None = None
    part_name: str
    part_number: str | None = None
    quantity: int = Field(default=1, ge=1)
    reason: str | None = None
    priority: PartRequestPriority = PartRequestPriority.NORMAL
    status: PartRequestStatus = PartRequestStatus.DRAFT

    @field_validator("priority", mode="before")
    @classmethod
    def accept_legacy_priority(cls, value):
        return LEGACY_PART_REQUEST_PRIORITY_CODES.get(value, value)

    @field_validator("status", mode="before")
    @classmethod
    def accept_legacy_status(cls, value):
        return LEGACY_PART_REQUEST_STATUS_CODES.get(value, value)


class PartRequestOut(PartRequestCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    priority: PartRequestPriority | str
    status: PartRequestStatus | str
    machine: MachineOut | None = None
    created_at: datetime


class TransferCreate(BaseModel):
    machine_id: int
    protocol_type: str = "Предаване"
    company_unit: str | None = None
    department: str | None = None
    vessel: str | None = None
    dock: str | None = None
    pier: str | None = None
    work_area: str | None = None
    location_text: str | None = None
    location_id: int | None = None
    handed_over_by: str | None = None
    accepted_by: str | None = None
    equipment: str | None = None
    hoses: str | None = None
    nozzles: str | None = None
    guns: str | None = None
    accessories: str | None = None
    condition_text: str | None = None
    remarks: str | None = None


class TransferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    machine_id: int
    protocol_type: str
    protocol_number: str
    batch_id: int | None = None
    batch_reference: str | None = None
    is_active: bool
    company_unit: str | None = None
    department: str | None = None
    vessel: str | None = None
    dock: str | None = None
    pier: str | None = None
    work_area: str | None = None
    location_text: str | None = None
    handed_over_by: str | None = None
    accepted_by: str | None = None
    equipment: str | None = None
    hoses: str | None = None
    nozzles: str | None = None
    guns: str | None = None
    accessories: str | None = None
    condition_text: str | None = None
    remarks: str | None = None
    issued_at: datetime | None = None
    returned_at: datetime | None = None
    return_condition_text: str | None = None
    return_result_text: str | None = None
    return_notes: str | None = None
    return_missing_equipment: str | None = None
    return_damage: str | None = None
    return_contamination: str | None = None
    return_cleaning_required: bool = False
    return_inspection_required: bool = True
    return_repair_required: bool = False
    created_at: datetime
    machine: MachineOut


class BulkIssueRequest(BaseModel):
    machine_ids: list[int]
    document_language: LanguageCode = LanguageCode.BG
    company_unit: str | None = None
    department: str | None = None
    vessel: str | None = None
    dock: str | None = None
    pier: str | None = None
    work_area: str | None = None
    location_text: str | None = None
    location_id: int | None = None
    handed_over_by: str | None = None
    accepted_by: str | None = None
    equipment: str | None = None
    hoses: str | None = None
    nozzles: str | None = None
    guns: str | None = None
    accessories: str | None = None
    condition_text: str | None = None
    remarks: str | None = None

    @model_validator(mode="after")
    def validate_machine_ids(self) -> BulkIssueRequest:
        if not self.machine_ids:
            raise ValueError("Изберете поне една машина.")
        if len(self.machine_ids) != len(set(self.machine_ids)):
            raise ValueError("Една машина не може да бъде избрана повече от веднъж.")
        return self


class ProtocolDocumentOut(BaseModel):
    id: int
    document_number: str | None = None
    language: str | None = None
    format: str
    filename: str
    download_endpoint: str


class BulkIssueTransferOut(BaseModel):
    transfer_id: int
    protocol_number: str
    machine_id: int
    machine_number: str
    documents: list[ProtocolDocumentOut]


class BulkIssueResponse(BaseModel):
    message: str
    batch_id: int
    batch_reference: str
    transfers: list[BulkIssueTransferOut]
    zip_download_endpoint: str


RETURN_WORKFLOW_STATUSES = {
    MachineStatus.RETURNED,
    MachineStatus.INSPECTION,
    MachineStatus.CLEANING,
    MachineStatus.REPAIR,
    MachineStatus.WAITING_APPROVAL,
    MachineStatus.WAITING_PARTS,
    MachineStatus.TESTING,
}


class BulkReturnItem(BaseModel):
    transfer_id: int
    machine_id: int
    condition_text: str = Field(min_length=1)
    result_text: str = Field(min_length=1)
    notes: str | None = None
    missing_equipment: str | None = None
    damage: str | None = None
    contamination: str | None = None
    cleaning_required: bool = False
    inspection_required: bool = True
    repair_required: bool = False
    returned_by: str | None = None
    accepted_by: str | None = None
    location_id: int | None = None
    next_status: MachineStatus = MachineStatus.INSPECTION

    @field_validator("next_status", mode="before")
    @classmethod
    def accept_legacy_next_status(cls, value):
        return LEGACY_MACHINE_STATUS_CODES.get(value, value)

    @field_validator("next_status")
    @classmethod
    def validate_next_status(cls, value: MachineStatus) -> MachineStatus:
        if value not in RETURN_WORKFLOW_STATUSES:
            raise ValueError(
                "След връщане машината трябва да премине към преглед, "
                "почистване, ремонт или тестване, а не директно към готовност."
            )
        return value


class BulkReturnRequest(BaseModel):
    items: list[BulkReturnItem]
    document_language: LanguageCode = LanguageCode.BG

    @model_validator(mode="after")
    def validate_items(self) -> BulkReturnRequest:
        if not self.items:
            raise ValueError("Изберете поне една машина за връщане.")
        machine_ids = [item.machine_id for item in self.items]
        transfer_ids = [item.transfer_id for item in self.items]
        if len(machine_ids) != len(set(machine_ids)):
            raise ValueError("Една машина не може да бъде върната повече от веднъж.")
        if len(transfer_ids) != len(set(transfer_ids)):
            raise ValueError("Едно предаване не може да бъде върнато повече от веднъж.")
        return self


class BatchProgressOut(BaseModel):
    batch_id: int
    batch_reference: str
    status: TransferBatchStatus
    total_machines: int
    returned_machines: int
    still_issued_machines: int


class BatchSummaryOut(BatchProgressOut):
    created_at: datetime


class BulkReturnItemOut(BaseModel):
    transfer_id: int
    machine_id: int
    machine_number: str
    new_status: MachineStatus
    returned_at: datetime
    documents: list[ProtocolDocumentOut] = Field(default_factory=list)


class BulkReturnResponse(BaseModel):
    message: str
    returned: list[BulkReturnItemOut]
    batches: list[BatchProgressOut]


class AvailabilityOut(BaseModel):
    machine_id: int
    machine_number: str
    brand: str
    pressure_bar: int
    status: MachineStatus | str
    status_label: str
    location: str | None = None
    available: bool
    unavailable_reason: str | None = None
    active_transfer_id: int | None = None
    protocol_number: str | None = None
    batch_reference: str | None = None
    issued_at: datetime | None = None
    current_recipient_or_location: str | None = None


class BatchTransferOut(BaseModel):
    transfer_id: int
    machine_id: int
    machine_number: str
    machine_name: str
    brand: str
    pressure_bar: int
    protocol_number: str
    is_active: bool
    issued_at: datetime | None = None
    returned_at: datetime | None = None
    current_status: MachineStatus | str
    location: str | None = None
    documents: list[ProtocolDocumentOut]


class BatchDetailsOut(BatchProgressOut):
    created_at: datetime
    transfers: list[BatchTransferOut]
    zip_download_endpoint: str


class PartCatalogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brand: str
    model: str | None = None
    manufacturer: str | None = None
    assembly: str | None = None
    position: str | None = None
    part_number: str
    description: str
    quantity: int | None = None
    unit: str | None = None
    technical_specification: str | None = None
    compatible_models: str | None = None
    compatible_machine_numbers: list[str] | None = None
    technical_notes: str | None = None
    alternative_part_number: str | None = None
    alternative_part_numbers: list[str] | None = None
    replacement_part_ids: list[int] | None = None
    supplier: str | None = None
    supplier_code: str | None = None
    estimated_price: float | None = None
    currency: str | None = None
    lead_time_days: int | None = None
    revision: str | None = None
    is_active: bool = True
    source_document: str | None = None
    source_page: int | None = None
    source_excerpt: str | None = None
    provenance_confidence: float | None = None
    is_verified: bool = False
    verified_at: datetime | None = None


class TechnicalDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brand: str
    category: str
    title: str


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entity_type: str
    entity_id: int | None = None
    action: str
    details: str | None = None
    user_id: int | None = None
    user_name: str | None = None
    operation_reference: str | None = None
    created_at: datetime
