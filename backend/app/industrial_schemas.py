from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import (
    ApprovalDecision,
    FieldType,
    LanguageCode,
    PartRequestPriority,
    RepairEventType,
    RepairStatus,
)


class CategoryCreate(BaseModel):
    code: str = Field(min_length=2, max_length=80, pattern=r"^[A-Z0-9_-]+$")
    name_bg: str = Field(min_length=2, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)
    name_ru: str | None = Field(default=None, max_length=255)
    description: str | None = None
    icon: str | None = Field(default=None, max_length=120)
    validation_rules: dict | None = None
    document_types: list[str] | None = None
    checklists: list[dict] | None = None
    status_codes: list[str] | None = None


class CategoryOut(CategoryCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime


class CategoryFieldCreate(BaseModel):
    code: str = Field(min_length=2, max_length=80, pattern=r"^[A-Z0-9_-]+$")
    label_bg: str = Field(min_length=2, max_length=255)
    label_en: str | None = Field(default=None, max_length=255)
    label_ru: str | None = Field(default=None, max_length=255)
    field_type: FieldType = FieldType.TEXT
    is_required: bool = False
    options: list[str] | None = None
    unit: str | None = Field(default=None, max_length=40)
    validation_rules: dict | None = None
    sort_order: int = 0

    @model_validator(mode="after")
    def validate_options(self) -> CategoryFieldCreate:
        if self.field_type == FieldType.SELECT and not self.options:
            raise ValueError("За поле от тип избор са необходими допустими стойности.")
        if self.field_type != FieldType.SELECT and self.options:
            raise ValueError("Допустими стойности се задават само за поле от тип избор.")
        return self


class CategoryFieldOut(CategoryFieldCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    is_active: bool


class LocationAdminCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None


class LocationAdminUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> LocationAdminUpdate:
        if not self.model_fields_set:
            raise ValueError("Не е подадена промяна за местоположението.")
        return self


class DepartmentCreate(BaseModel):
    code: str = Field(min_length=2, max_length=80, pattern=r"^[A-Z0-9_-]+$")
    name_bg: str = Field(min_length=1, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)
    name_ru: str | None = Field(default=None, max_length=255)
    description: str | None = None


class DepartmentUpdate(BaseModel):
    code: str | None = Field(
        default=None, min_length=2, max_length=80, pattern=r"^[A-Z0-9_-]+$"
    )
    name_bg: str | None = Field(default=None, min_length=1, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)
    name_ru: str | None = Field(default=None, max_length=255)
    description: str | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> DepartmentUpdate:
        if not self.model_fields_set:
            raise ValueError("Не е подадена промяна за отдела.")
        return self


class CustomFieldValueInput(BaseModel):
    field_id: int
    value: str | None = None


class CustomFieldValuesUpdate(BaseModel):
    values: list[CustomFieldValueInput]

    @model_validator(mode="after")
    def reject_duplicates(self) -> CustomFieldValuesUpdate:
        identifiers = [item.field_id for item in self.values]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Едно потребителско поле е подадено повече от веднъж.")
        return self


class AttachmentCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=3, max_length=150)
    content_base64: str = Field(min_length=1)
    kind: str = Field(default="DOCUMENT", max_length=40)
    description: str | None = None
    stage: str = Field(default="GENERAL", max_length=40)


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    media_type: str
    sha256: str
    created_at: datetime
    description: str | None = None
    kind: str | None = None
    caption: str | None = None
    stage: str | None = None
    download_endpoint: str


class MachineEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    reference: str | None = None
    previous_status: str | None = None
    new_status: str | None = None
    details: dict | None = None
    user_id: int | None = None
    created_at: datetime


class RepairCaseCreate(BaseModel):
    machine_id: int
    reported_problem: str = Field(min_length=2)
    repair_type: str | None = Field(default=None, max_length=120)
    severity: str | None = Field(default=None, max_length=80)
    condition_before: str | None = None
    reported_by_name: str | None = Field(default=None, max_length=255)
    symptoms: str | None = None
    required_work: str | None = None
    diagnosis: str | None = None
    responsible_user_id: int | None = None
    cleaning_required: bool = False
    test_required: bool = True
    target_date: datetime | None = None


class RepairCaseUpdate(BaseModel):
    reported_problem: str | None = None
    condition_before: str | None = None
    diagnosis: str | None = None
    work_performed: str | None = None
    result: str | None = None
    condition_after: str | None = None
    symptoms: str | None = None
    required_work: str | None = None
    required_parts_text: str | None = None
    removed_parts_text: str | None = None
    diagnostic_cleaning: str | None = None
    diagnosis_minutes: int | None = Field(default=None, ge=0, le=100000)
    repair_minutes: int | None = Field(default=None, ge=0, le=100000)
    testing_minutes: int | None = Field(default=None, ge=0, le=100000)
    advance_to_final: bool = False
    status: RepairStatus | None = None
    responsible_user_id: int | None = None
    severity: str | None = Field(default=None, max_length=80)
    cleaning_required: bool | None = None
    inspection_complete: bool = False
    cleaning_complete: bool = False
    test_passed: bool | None = None
    test_details: str | None = None
    test_method: str | None = None
    test_pressure_bar: int | None = Field(default=None, ge=0, le=10000)
    leaks_detected: bool | None = None
    electrical_test_result: str | None = None
    functional_test_result: str | None = None
    target_date: datetime | None = None


class RepairProtocolCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=10, max_length=2000)
    language: LanguageCode = LanguageCode.BG

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return value.strip()


class RepairParticipantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int | None = None
    full_name: str | None = Field(default=None, min_length=3, max_length=255)
    job_title: str | None = Field(default=None, max_length=255)
    contribution: str | None = Field(default=None, max_length=1000)
    minutes_worked: int = Field(ge=1, le=100000)

    @field_validator("full_name", "job_title", "contribution")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    @model_validator(mode="after")
    def require_identity(self) -> "RepairParticipantCreate":
        if self.user_id is None and not self.full_name:
            raise ValueError("Изберете потребител или въведете трите имена на участника.")
        return self


class RepairEventCreate(BaseModel):
    event_type: RepairEventType
    description: str | None = None
    structured_data: dict | None = None
    next_status: RepairStatus | None = None


class RepairPartCreate(BaseModel):
    catalog_part_id: int | None = None
    part_number: str | None = Field(default=None, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    quantity: float = Field(gt=0)
    unit: str | None = Field(default=None, max_length=40)
    source: str | None = Field(default=None, max_length=255)


class RepairEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    status_before: str | None = None
    status_after: str | None = None
    description: str | None = None
    structured_data: dict | None = None
    user_id: int
    created_at: datetime


class RepairPartOut(RepairPartCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repair_id: int
    created_by_id: int
    created_at: datetime


class RepairCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repair_reference: str | None = None
    machine_id: int
    reported_problem: str
    diagnosis: str | None = None
    work_performed: str | None = None
    result: str | None = None
    status: str
    repair_type: str | None = None
    severity: str | None = None
    condition_before: str | None = None
    condition_after: str | None = None
    diagnostic_cleaning: str | None = None
    cleaning_required: bool
    cleaning_completed_at: datetime | None = None
    inspection_completed_at: datetime | None = None
    test_required: bool
    test_passed: bool | None = None
    test_details: str | None = None
    responsible_user_id: int | None = None
    accepted_by_id: int | None = None
    approved_by_id: int | None = None
    approved_at: datetime | None = None
    target_date: datetime | None = None
    opened_at: datetime
    closed_at: datetime | None = None
    machine_number: str
    machine_name: str
    events: list[RepairEventOut]
    parts_used: list[RepairPartOut]
    attachments: list[AttachmentOut]


class PartRequestLineCreate(BaseModel):
    catalog_part_id: int | None = None
    position: str | None = Field(default=None, max_length=40)
    part_number: str | None = Field(default=None, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    quantity: int = Field(ge=1)
    unit: str | None = Field(default=None, max_length=40)
    reason: str | None = None
    source_document: str | None = Field(default=None, max_length=700)
    source_page: int | None = Field(default=None, ge=1)
    is_unknown_part: bool = False
    assembly: str | None = Field(default=None, max_length=255)
    note: str | None = None

    @model_validator(mode="after")
    def validate_unknown_part(self) -> PartRequestLineCreate:
        if self.is_unknown_part:
            if self.catalog_part_id is not None or self.part_number:
                raise ValueError(
                    "Част без потвърден part number не може да съдържа каталожен идентификатор или part number."
                )
            if not (self.assembly or "").strip():
                raise ValueError("За непозната част трябва да бъде посочен възел.")
        return self


class MultiPartRequestCreate(BaseModel):
    machine_id: int | None = None
    repair_id: int | None = None
    repair_kit_id: int | None = None
    repair_kit_mode: Literal["COMPONENTS", "KIT"] = "COMPONENTS"
    priority: PartRequestPriority = PartRequestPriority.NORMAL
    language: LanguageCode = LanguageCode.BG
    reason: str | None = None
    department: str | None = Field(default=None, max_length=255)
    submit_for_approval: bool = False
    lines: list[PartRequestLineCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_duplicate_catalog_parts(self) -> MultiPartRequestCreate:
        identifiers = [
            item.catalog_part_id for item in self.lines if item.catalog_part_id is not None
        ]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Една каталожна част е добавена повече от веднъж.")
        return self


class PartRequestLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: int
    catalog_part_id: int | None = None
    position: str | None = None
    part_number: str | None = None
    description: str
    # Legacy Float persistence remains readable without weakening current writes.
    quantity: float
    unit: str | None = None
    reason: str | None = None
    source_document: str | None = None
    source_page: int | None = None
    delivered_quantity: float
    is_unknown_part: bool = False
    assembly: str | None = None
    note: str | None = None
    linked_catalog_part_id: int | None = None
    linked_part_number: str | None = None
    linked_part_description: str | None = None
    linked_by_id: int | None = None
    linked_at: datetime | None = None
    link_note: str | None = None


class PartRequestApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    decision: str
    note: str | None = None
    decided_by_id: int
    decided_by_name: str | None = None
    decided_at: datetime


class PartRequestQuantityCompatibilityOut(BaseModel):
    status: Literal["COMPATIBLE", "LEGACY_FRACTIONAL"]
    affected_line_ids: list[int]
    recovery_action: Literal[
        "NONE",
        "CREATE_REPLACEMENT",
        "REJECT_AND_RECREATE",
        "CANCEL_AND_RECREATE",
        "HISTORICAL_ONLY",
    ]
    affected_lines: list[dict] = Field(default_factory=list)


class MultiPartRequestOut(BaseModel):
    id: int
    request_reference: str
    machine_id: int | None = None
    machine_number: str | None = None
    repair_id: int | None = None
    repair_reference: str | None = None
    repair_kit_id: int | None = None
    repair_kit_mode: str | None = None
    priority: str
    status: str
    language: str
    reason: str | None = None
    requested_by_id: int | None = None
    requested_by_name: str | None = None
    decided_by_name: str | None = None
    submitted_at: datetime | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    created_at: datetime
    quantity_compatibility: PartRequestQuantityCompatibilityOut
    lines: list[PartRequestLineOut]
    approvals: list[PartRequestApprovalOut]
    attachments: list[AttachmentOut]
    documents: list[dict]


class PartRequestPendingActionCountOut(BaseModel):
    pending_action_count: int


class PartRequestDecision(BaseModel):
    decision: ApprovalDecision
    note: str | None = None


class PartRequestDeliveryLine(BaseModel):
    line_id: int
    delivered_quantity: int = Field(ge=0)


class UnknownPartRequestCreate(BaseModel):
    machine_id: int
    repair_id: int | None = None
    assembly: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=500)
    quantity: int = Field(ge=1)
    unit: str | None = Field(default=None, max_length=40)
    note: str | None = None
    priority: PartRequestPriority = PartRequestPriority.NORMAL
    language: LanguageCode = LanguageCode.BG
    department: str | None = Field(default=None, max_length=255)
    photo: AttachmentCreate

    @model_validator(mode="after")
    def require_image(self) -> UnknownPartRequestCreate:
        if self.photo.media_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("Снимката на непознатата част трябва да бъде JPEG, PNG или WebP.")
        return self


class UnknownPartCatalogLink(BaseModel):
    catalog_part_id: int
    note: str | None = None


class PartRequestFulfillmentUpdate(BaseModel):
    status: Literal["ORDERED", "PARTIALLY_DELIVERED", "DELIVERED", "CANCELLED"]
    supplier: str | None = Field(default=None, max_length=255)
    note: str | None = None
    lines: list[PartRequestDeliveryLine] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_duplicate_lines(self) -> PartRequestFulfillmentUpdate:
        identifiers = [item.line_id for item in self.lines]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Един ред е подаден повече от веднъж.")
        return self


class CatalogPartCreate(BaseModel):
    brand: str = Field(min_length=1, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    manufacturer: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=120)
    name_bg: str | None = Field(default=None, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)
    name_ru: str | None = Field(default=None, max_length=255)
    original_name: str | None = Field(default=None, max_length=500)
    assembly: str | None = Field(default=None, max_length=255)
    position: str | None = Field(default=None, max_length=40)
    part_number: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    quantity: int | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=40)
    technical_specification: str | None = None
    compatible_models: str | None = None
    compatible_machine_numbers: list[str] | None = None
    technical_notes: str | None = None
    supplier: str | None = Field(default=None, max_length=255)
    supplier_code: str | None = Field(default=None, max_length=120)
    estimated_price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    lead_time_days: int | None = Field(default=None, ge=0)
    revision: str | None = Field(default=None, max_length=80)
    is_active: bool = True
    alternative_part_number: str | None = Field(default=None, max_length=120)
    alternative_part_numbers: list[str] | None = None
    replacement_part_ids: list[int] | None = None
    source_document: str | None = Field(default=None, max_length=500)
    source_page: int | None = Field(default=None, ge=1)
    source_excerpt: str | None = None
    provenance_confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @field_validator("compatible_machine_numbers")
    @classmethod
    def reject_duplicate_machines(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("Една машина не може да бъде добавена два пъти към съвместимостта.")
        return value

    @field_validator("alternative_part_numbers")
    @classmethod
    def validate_alternative_numbers(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [item.strip() for item in value if item.strip()]
        if len(normalized) != len(value) or len(normalized) != len(set(normalized)):
            raise ValueError("Алтернативните номера трябва да са непразни и уникални.")
        if any(len(item) > 120 for item in normalized):
            raise ValueError("Алтернативен номер не може да е по-дълъг от 120 знака.")
        return normalized

    @field_validator("replacement_part_ids")
    @classmethod
    def validate_replacements(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("Една заместваща част не може да бъде посочена повече от веднъж.")
        return value


class CatalogPartUpdate(CatalogPartCreate):
    pass


class HotspotCreate(BaseModel):
    technical_document_id: int | None = None
    page_number: int = Field(ge=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(default=0.03, gt=0, le=1)
    height: float = Field(default=0.03, gt=0, le=1)
    label: str | None = Field(default=None, max_length=120)
    provenance: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class RepairKitComponentCreate(BaseModel):
    part_id: int
    quantity: float = Field(gt=0)
    is_optional: bool = False
    note: str | None = None


class RepairKitCreate(BaseModel):
    code: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=255)
    brand: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    compatible_models: str | None = None
    revision: str | None = Field(default=None, max_length=80)
    assembly: str | None = Field(default=None, max_length=255)
    source_document: str | None = Field(default=None, max_length=700)
    source_page: int | None = Field(default=None, ge=1)
    provenance: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    components: list[RepairKitComponentCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_duplicate_parts(self) -> RepairKitCreate:
        part_ids = [item.part_id for item in self.components]
        if len(part_ids) != len(set(part_ids)):
            raise ValueError("Една част е включена повече от веднъж в комплекта.")
        return self


class TemplateCreate(BaseModel):
    code: str = Field(min_length=2, max_length=80, pattern=r"^[A-Z0-9_-]+$")
    document_type: str = Field(min_length=2, max_length=80)
    name_bg: str = Field(min_length=2, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)
    name_ru: str | None = Field(default=None, max_length=255)


class TemplateVersionCreate(BaseModel):
    language: LanguageCode = LanguageCode.BG
    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=3, max_length=150)
    content_base64: str = Field(min_length=1)
    layout_contract: dict
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    required_fields: list[str] = Field(default_factory=list)
    numbering_rule: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    change_note: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_template_period(self) -> TemplateVersionCreate:
        if self.effective_from and self.effective_to and self.effective_to <= self.effective_from:
            raise ValueError("Краят на валидността трябва да бъде след началото.")
        if len(self.required_fields) != len(set(self.required_fields)):
            raise ValueError("Задължително поле е посочено повече от веднъж.")
        return self


class TechnicalDocumentUpload(BaseModel):
    brand: str = Field(min_length=1, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    category: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=500)
    language: LanguageCode | None = None
    revision: str | None = Field(default=None, max_length=80)
    source_label: str | None = Field(default=None, max_length=500)
    document_date: datetime | None = None
    tags: list[str] | None = None
    extracted_text: str | None = None
    page_count: int | None = Field(default=None, ge=1)
    notes: str | None = None
    linked_machine_numbers: list[str] | None = None
    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=3, max_length=150)
    content_base64: str = Field(min_length=1)
    change_note: str | None = None

    @field_validator("tags", "linked_machine_numbers")
    @classmethod
    def reject_duplicate_list_values(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("Списъкът съдържа повторена стойност.")
        return value


class ImportPreviewRequest(BaseModel):
    records: list[dict] = Field(min_length=1, max_length=5000)


class ImportConfirmRequest(BaseModel):
    preview_token: str = Field(min_length=20, max_length=500)
