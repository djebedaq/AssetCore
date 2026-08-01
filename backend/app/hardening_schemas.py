from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import LanguageCode, LicenseType, OfficialDocumentStatus, UserRole


def _clean(value: str | None) -> str | None:
    return value.strip() if value is not None else None


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(min_length=1, max_length=120)
    middle_name: str | None = Field(default=None, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    job_title: str = Field(min_length=2, max_length=255)
    department_id: int | None = None
    preferred_language: LanguageCode | None = None
    legal_name_exception: bool = False
    legal_name_exception_reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_identity(self):
        for field in ("first_name", "middle_name", "last_name", "job_title"):
            setattr(self, field, _clean(getattr(self, field)))
        self.legal_name_exception_reason = _clean(self.legal_name_exception_reason)
        if not self.middle_name and not self.legal_name_exception:
            raise ValueError(
                "Бащиното име е задължително. При законово изключение посочете причина."
            )
        if self.legal_name_exception and not self.legal_name_exception_reason:
            raise ValueError("Посочете основание за законовото изключение.")
        return self


class OwnerTransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_user_id: int
    current_password: str = Field(min_length=1)
    reason: str = Field(min_length=10, max_length=2000)


class OwnerStatusOut(BaseModel):
    owner_user_id: int
    owner_name: str
    owner_email: str
    role: UserRole
    designated_at: datetime
    designation_version: int


class EmergencyAccessStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1)
    reason: str = Field(min_length=10, max_length=2000)
    duration_minutes: int = Field(default=30, ge=5, le=60)


class EmergencyAccessEnd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1)
    reason: str = Field(min_length=10, max_length=2000)


class EmergencyAccessStatusOut(BaseModel):
    active: bool
    session_id: int | None = None
    started_at: datetime | None = None
    expires_at: datetime | None = None
    owner_name: str | None = None
    mfa_verified: bool = False
    message: str


class LicenseEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: dict
    signature: str = Field(min_length=40, max_length=1000)


class LicenseStatusOut(BaseModel):
    state: str
    message: str
    read_only: bool
    license_id: str | None = None
    license_type: LicenseType | None = None
    client_name: str | None = None
    rightsholder: str | None = None
    installation_id: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    grace_until: datetime | None = None
    issued_at: datetime | None = None
    activated_at: datetime | None = None
    support_until: datetime | None = None
    checked_at: datetime
    modules: list[str] = Field(default_factory=list)
    max_users: int | None = None
    max_assets: int | None = None
    environment: str | None = None
    allowed_domains: list[str] = Field(default_factory=list)
    max_installations: int | None = None
    version: int | None = None


class ExternalSignerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(min_length=1, max_length=120)
    middle_name: str | None = Field(default=None, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    job_title: str = Field(min_length=2, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    participant_role: str = Field(min_length=2, max_length=120)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("first_name", "middle_name", "last_name", "job_title", "company", "participant_role", "note")
    @classmethod
    def strip_values(cls, value: str | None) -> str | None:
        return _clean(value)


class ExternalSignerOut(ExternalSignerCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_by_id: int
    created_at: datetime
    updated_at: datetime


class ExternalSignerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    middle_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    job_title: str | None = Field(default=None, min_length=2, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    participant_role: str | None = Field(default=None, min_length=2, max_length=120)
    note: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None

    @field_validator("first_name", "middle_name", "last_name", "job_title", "company", "participant_role", "note")
    @classmethod
    def strip_values(cls, value: str | None) -> str | None:
        return _clean(value)


class SignatureSlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_type: str
    code: str
    label_bg: str
    label_en: str | None = None
    label_ru: str | None = None
    required: bool
    allowed_participant_kind: str
    sequence: int
    signing_mode: str
    is_active: bool


class SignatureSlotUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label_bg: str | None = Field(default=None, min_length=2, max_length=255)
    label_en: str | None = Field(default=None, min_length=2, max_length=255)
    label_ru: str | None = Field(default=None, min_length=2, max_length=255)
    required: bool | None = None
    allowed_participant_kind: str | None = Field(default=None, pattern="^(ANY|INTERNAL|EXTERNAL)$")
    sequence: int | None = Field(default=None, ge=1, le=100)
    signing_mode: str | None = Field(default=None, pattern="^(PARALLEL|SEQUENTIAL)$")
    is_active: bool | None = None


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=5, max_length=2000)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 5:
            raise ValueError("Причината трябва да съдържа поне 5 знака.")
        return cleaned


class ParticipantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_code: str = Field(pattern=r"^[A-Z0-9_]{2,80}$")
    operation_role: str = Field(min_length=2, max_length=120)
    user_id: int | None = None
    external_signer_id: int | None = None

    @model_validator(mode="after")
    def exactly_one_identity(self):
        if (self.user_id is None) == (self.external_signer_id is None):
            raise ValueError("Изберете точно един вътрешен или външен участник.")
        return self


class OfficialDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_number: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9._/-]+$")
    document_type: str = Field(min_length=2, max_length=80)
    language: LanguageCode = LanguageCode.BG
    machine_id: int | None = None
    transfer_id: int | None = None
    batch_id: int | None = None
    snapshot: dict
    docx_base64: str | None = None
    pdf_base64: str | None = None
    participants: list[ParticipantInput] = Field(default_factory=list)


class OfficialDocumentVersionOut(BaseModel):
    id: int
    version: int
    status: OfficialDocumentStatus
    language: LanguageCode
    snapshot_sha256: str
    docx_sha256: str | None = None
    pdf_sha256: str | None = None
    correction_reason: str | None = None
    created_at: datetime
    finalized_at: datetime | None = None


class OfficialDocumentOut(BaseModel):
    id: int
    document_number: str
    document_type: str
    machine_id: int | None = None
    transfer_id: int | None = None
    batch_id: int | None = None
    created_at: datetime
    current_version: OfficialDocumentVersionOut
    signed_count: int
    required_count: int
    participants: list[dict] = Field(default_factory=list)


class ParticipantsAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participants: list[ParticipantInput] = Field(min_length=1)


class SupersedeDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=10, max_length=2000)
    snapshot: dict
    docx_base64: str | None = None
    pdf_base64: str | None = None
    participants: list[ParticipantInput] = Field(default_factory=list)


class SignatureSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participant_id: int
    expires_minutes: int = Field(default=30, ge=5, le=1440)


class SignatureSessionOut(BaseModel):
    signing_token: str
    signing_endpoint: str
    expires_at: datetime


class StrokePoint(BaseModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    t: float = Field(ge=0)
    pressure: float | None = Field(default=None, ge=0, le=1)


class SignatureSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent_accepted: bool
    consent_text: str = Field(min_length=20, max_length=2000)
    strokes: list[list[StrokePoint]]
    image_base64: str = Field(min_length=20)
    canvas_width: int = Field(ge=200, le=4096)
    canvas_height: int = Field(ge=100, le=4096)

    @model_validator(mode="after")
    def validate_signature(self):
        if not self.consent_accepted:
            raise ValueError("Трябва да приемете текста за съгласие.")
        point_count = sum(len(stroke) for stroke in self.strokes)
        if len(self.strokes) < 1 or point_count < 8:
            raise ValueError("Подписът е празен или твърде кратък.")
        return self
