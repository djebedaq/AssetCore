from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import MachineStatus


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class MachineBase(BaseModel):
    inventory_number: str
    name: str
    category: str = "HPWJ"
    brand: str
    model: str | None = None
    pressure_bar: int = 500
    serial_number: str | None = None
    status: MachineStatus = MachineStatus.READY
    location_id: int | None = None
    notes: str | None = None


class MachineCreate(MachineBase):
    pass


class MachineUpdate(BaseModel):
    name: str | None = None
    brand: str | None = None
    model: str | None = None
    pressure_bar: int | None = None
    serial_number: str | None = None
    status: MachineStatus | None = None
    location_id: int | None = None
    notes: str | None = None


class MachineOut(MachineBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    location: LocationOut | None = None
    created_at: datetime
    updated_at: datetime


class RepairCreate(BaseModel):
    machine_id: int
    reported_problem: str
    diagnosis: str | None = None
    work_performed: str | None = None
    result: str | None = None
    status: str = "Приета"


class RepairUpdate(BaseModel):
    diagnosis: str | None = None
    work_performed: str | None = None
    result: str | None = None
    status: str | None = None
    close: bool = False


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
    priority: str = "Нормален"
    status: str = "Чернова"


class PartRequestOut(PartRequestCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    machine: MachineOut | None = None
    created_at: datetime


class TransferCreate(BaseModel):
    machine_id: int
    protocol_type: str = "Предаване"
    company_unit: str | None = None
    vessel: str | None = None
    location_text: str | None = None
    location_id: int | None = None
    handed_over_by: str | None = None
    accepted_by: str | None = None
    equipment: str | None = None
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
    vessel: str | None = None
    location_text: str | None = None
    handed_over_by: str | None = None
    accepted_by: str | None = None
    equipment: str | None = None
    condition_text: str | None = None
    remarks: str | None = None
    issued_at: datetime | None = None
    returned_at: datetime | None = None
    return_condition_text: str | None = None
    return_result_text: str | None = None
    return_notes: str | None = None
    created_at: datetime
    machine: MachineOut


class BulkIssueRequest(BaseModel):
    machine_ids: list[int]
    company_unit: str | None = None
    vessel: str | None = None
    location_text: str | None = None
    location_id: int | None = None
    handed_over_by: str | None = None
    accepted_by: str | None = None
    equipment: str | None = None
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
    returned_by: str | None = None
    accepted_by: str | None = None
    location_id: int | None = None
    next_status: MachineStatus = MachineStatus.INSPECTION

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
    status: str
    total_machines: int
    returned_machines: int
    still_issued_machines: int


class BatchSummaryOut(BatchProgressOut):
    created_at: datetime


class BulkReturnItemOut(BaseModel):
    transfer_id: int
    machine_id: int
    machine_number: str
    new_status: str
    returned_at: datetime


class BulkReturnResponse(BaseModel):
    message: str
    returned: list[BulkReturnItemOut]
    batches: list[BatchProgressOut]


class AvailabilityOut(BaseModel):
    machine_id: int
    machine_number: str
    brand: str
    pressure_bar: int
    status: str
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
    current_status: str
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
    assembly: str | None = None
    position: str | None = None
    part_number: str
    description: str
    quantity: int | None = None
    source_document: str | None = None
    source_page: int | None = None


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
