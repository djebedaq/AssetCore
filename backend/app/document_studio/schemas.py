from __future__ import annotations

import re
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_TYPES = ("TRANSFER_ISSUE", "TRANSFER_RETURN", "REPAIR_PROTOCOL", "PART_REQUEST")
# Identifiers refer to the existing canonical renderer vocabulary. No expressions
# are accepted and no business values are synthesized by this foundation.
FIELD_CATALOG = {
    "DOCUMENT_NUMBER": "operation", "CREATION_DATE": "operation",
    "PREPARER_NAME": "operation", "SIGNATURE_STATUS": "operation",
    "MACHINE_NUMBER": "machine", "MACHINE_NAME": "machine",
    "BRAND": "machine", "MODEL": "machine", "SERIAL_NUMBER": "machine",
    "REMARKS": "operation", "REPAIR_REFERENCE": "repair", "REPORTED_PROBLEM": "repair",
    "DIAGNOSIS": "repair", "WORK_PERFORMED": "repair", "TEST_RESULT": "repair",
    "DECISION": "request",
    "COMPANY_NAME": "company", "COMPANY_ADDRESS": "company",
    "COMPANY_REGISTRATION": "company", "COMPANY_CONTACTS": "company",
}
TABLE_CATALOG = {"PARTS_USED": "REPAIR_PROTOCOL", "REPAIR_EVENTS": "REPAIR_PROTOCOL",
                 "REQUEST_LINES": "PART_REQUEST"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class CompanyIdentity(StrictModel):
    legal_name: str = Field(default="AssetCore", min_length=1, max_length=255)
    short_name: str = Field(default="", max_length=100)
    registration_number: str = Field(default="", max_length=100)
    vat_number: str = Field(default="", max_length=100)
    address: str = Field(default="", max_length=700)
    city: str = Field(default="", max_length=150)
    country: str = Field(default="", max_length=150)
    phone: str = Field(default="", max_length=80)
    email: str = Field(default="", max_length=254)
    website: str = Field(default="", max_length=500)
    primary_color: str = "#183153"
    secondary_color: str = "#64748b"
    default_language: Literal["bg", "en", "ru"] = "bg"
    timezone: str = Field(default="UTC", max_length=100)
    primary_logo_id: int | None = Field(default=None, gt=0)
    secondary_logo_id: int | None = Field(default=None, gt=0)
    identity_image_ids: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list, max_length=20)

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def color(cls, value):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("studio_invalid_color")
        return value.lower()

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        if value and not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value):
            raise ValueError("studio_invalid_email")
        return value

    @field_validator("website")
    @classmethod
    def website_address(cls, value):
        if value:
            parsed = urlsplit(value)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                    or parsed.password or any(c.isspace() for c in value)):
                raise ValueError("studio_invalid_website")
        # Stored text only: never fetched, embedded or used as an image source.
        return value

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("studio_invalid_timezone") from None
        return value

    @field_validator("identity_image_ids")
    @classmethod
    def unique_images(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("studio_duplicate_images")
        return value


class IdentityUpdate(StrictModel):
    expected_revision: int = Field(ge=0)
    identity: CompanyIdentity


class ImageUpload(StrictModel):
    filename: str = Field(min_length=1, max_length=120, pattern=r"^[^/\\\x00-\x1f]+\.(?i:png|jpg|jpeg)$")
    media_type: Literal["image/png", "image/jpeg"]
    content_base64: str = Field(min_length=1, max_length=2_800_000)
    purpose: Literal["PRIMARY", "SECONDARY", "IDENTITY"]


class Page(StrictModel):
    format: Literal["A4"] = "A4"
    orientation: Literal["portrait", "landscape"] = "portrait"
    margin_mm: float = Field(default=15, ge=5, le=40, allow_inf_nan=False)


class Style(StrictModel):
    font: Literal["Arial", "Liberation Sans", "DejaVu Sans"] = "Arial"
    size_pt: float = Field(default=11, ge=6, le=48, allow_inf_nan=False)
    color: str = Field(default="#183153", pattern=r"^#[0-9a-fA-F]{6}$")
    align: Literal["left", "center", "right"] = "left"
    spacing_mm: float = Field(default=2, ge=0, le=30, allow_inf_nan=False)


class BlockBase(StrictModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    region: Literal["body", "header", "footer"] = "body"
    style: Style = Field(default_factory=Style)


class TextBlock(BlockBase):
    type: Literal["text", "heading"]
    text: str = Field(max_length=10_000)


class FieldBlock(BlockBase):
    type: Literal["field"]
    field: str

    @field_validator("field")
    @classmethod
    def allowed_field(cls, value):
        if value not in FIELD_CATALOG:
            raise ValueError("studio_unknown_field")
        return value


class ImageBlock(BlockBase):
    type: Literal["image", "logo"]
    image_id: int = Field(gt=0)
    width_mm: float = Field(default=40, ge=5, le=180, allow_inf_nan=False)
    height_mm: float = Field(default=20, ge=5, le=100, allow_inf_nan=False)


class TableColumn(StrictModel):
    key: Literal["position", "description", "quantity", "unit", "part_number", "note"]
    label: str = Field(min_length=1, max_length=100)
    width_percent: float = Field(gt=0, le=100, allow_inf_nan=False)


class DynamicTable(BlockBase):
    type: Literal["dynamic_table"]
    source: Literal["PARTS_USED", "REPAIR_EVENTS", "REQUEST_LINES"]
    columns: list[TableColumn] = Field(min_length=1, max_length=6)
    repeat_header: Literal[True] = True
    flow: Literal[True] = True

    @model_validator(mode="after")
    def column_widths(self):
        if abs(sum(c.width_percent for c in self.columns) - 100) > 0.01:
            raise ValueError("studio_table_width")
        if len({c.key for c in self.columns}) != len(self.columns):
            raise ValueError("studio_duplicate_columns")
        return self


class StaticTable(BlockBase):
    type: Literal["table"]
    rows: list[list[Annotated[str, Field(max_length=2000)]]] = Field(min_length=1, max_length=50)

    @field_validator("rows")
    @classmethod
    def rectangular(cls, value):
        if not 1 <= len(value[0]) <= 8 or any(len(r) != len(value[0]) for r in value):
            raise ValueError("studio_table_shape")
        return value


class SignatureBlock(BlockBase):
    type: Literal["signature"]
    slot: Literal["LEFT_SIGNATURE", "RIGHT_SIGNATURE"]
    required: Literal[True] = True


class SystemBlock(BlockBase):
    type: Literal["line", "frame", "page_number", "page_break", "qr"]


class ConditionalBlock(BlockBase):
    type: Literal["conditional"]
    when_field: str
    text: str = Field(max_length=10_000)

    @field_validator("when_field")
    @classmethod
    def known_field(cls, value):
        return FieldBlock.allowed_field(value)


Block = Annotated[TextBlock | FieldBlock | ImageBlock | DynamicTable | StaticTable
                  | SignatureBlock | SystemBlock | ConditionalBlock, Field(discriminator="type")]


class Layout(StrictModel):
    schema_version: Literal[1] = 1
    page: Page = Field(default_factory=Page)
    # Flow is authoritative in v1. Fixed placement is intentionally not yet
    # supported: long text/tables cannot overlap signature areas.
    positioning: Literal["flow"] = "flow"
    blocks: list[Block] = Field(max_length=200)

    @model_validator(mode="after")
    def identifiers(self):
        if len({b.id for b in self.blocks}) != len(self.blocks):
            raise ValueError("studio_duplicate_block_ids")
        if any(b.region != "body" and b.type in {"dynamic_table", "signature", "page_break"}
               for b in self.blocks):
            raise ValueError("studio_invalid_region")
        return self


class DraftCreate(StrictModel):
    title: str = Field(min_length=1, max_length=255)
    language: Literal["bg", "en", "ru"] = "bg"
    base_version_id: int | None = Field(default=None, gt=0)


class DraftUpdate(StrictModel):
    expected_revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=255)
    layout: Layout


class TemplateCreate(StrictModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Z0-9_-]+$")
    document_type: Literal["TRANSFER_ISSUE", "TRANSFER_RETURN", "REPAIR_PROTOCOL", "PART_REQUEST"]
    name_bg: str = Field(min_length=1, max_length=255)
    name_en: str = Field(min_length=1, max_length=255)
    name_ru: str = Field(min_length=1, max_length=255)


def initial_layout(document_type: str) -> Layout:
    blocks = [{"id": field.lower(), "type": "field", "field": field}
              for field in ("DOCUMENT_NUMBER", "PREPARER_NAME", "SIGNATURE_STATUS")]
    slots = ["LEFT_SIGNATURE"]
    if document_type != "REPAIR_PROTOCOL":
        slots.append("RIGHT_SIGNATURE")
    blocks += [{"id": slot.lower(), "type": "signature", "slot": slot} for slot in slots]
    return Layout.model_validate({"blocks": blocks})


def validate_workflow(layout: Layout, document_type: str) -> None:
    required = initial_layout(document_type)
    for block in required.blocks:
        if sum(b.type == block.type and (
            getattr(b, "field", None) == getattr(block, "field", None)
            and getattr(b, "slot", None) == getattr(block, "slot", None)
        ) for b in layout.blocks) != 1:
            raise ValueError("studio_required_block")
    for block in layout.blocks:
        if isinstance(block, DynamicTable) and TABLE_CATALOG[block.source] != document_type:
            raise ValueError("studio_incompatible_table")
        field = block.field if isinstance(block, FieldBlock) else block.when_field if isinstance(block, ConditionalBlock) else None
        if field:
            group = FIELD_CATALOG[field]
            if ((group == "repair" and document_type != "REPAIR_PROTOCOL")
                    or (group == "request" and document_type != "PART_REQUEST")):
                raise ValueError("studio_incompatible_field")
