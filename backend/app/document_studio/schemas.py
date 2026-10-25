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
FIELD_CATALOG.update({code: group for group, codes in {
    "machine": "EQUIPMENT_TYPE MACHINE_LOCATION PRESSURE_BAR",
    "operation": "PREPARER_JOB_TITLE LEFT_SIGNER_NAME LEFT_SIGNER_JOB_TITLE RIGHT_SIGNER_NAME RIGHT_SIGNER_JOB_TITLE BATCH_REFERENCE",
    "transfer": "CONDITION_TEXT USAGE_TEXT",
    "repair": "CONDITION_BEFORE CONDITION_AFTER REQUIRED_WORK REQUIRED_PARTS REMOVED_PARTS FINAL_RESULT REPAIRER_NAMES ACCEPTED_BY_NAME APPROVED_BY_NAME DIAGNOSTIC_CLEANING DIAGNOSIS_DURATION REPAIR_DURATION TESTING_DURATION TOTAL_WORK_DURATION PARTICIPANT_TOTAL_DURATION",
    "request": "REQUESTER_NAME DEPARTMENT APPROVAL_DATE APPROVER_NAME",
}.items() for code in codes.split()})
FIELD_CATALOG.update({code: group for group, codes in {
    "machine": "MODEL_DISPLAY MANUFACTURER",
    "operation": "LEFT_SIGNER_ROLE RIGHT_SIGNER_ROLE LEFT_SIGNER_ORGANIZATION RIGHT_SIGNER_ORGANIZATION",
    "repair": "SOURCE_RETURN_REFERENCE ACCEPTANCE_DATE COMPLETION_DATE OWNERSHIP REPAIR_START REPAIR_END HANDED_OVER_NAME APPROVED_BY_JOB_TITLE REPAIR_STATUS SYMPTOMS TEST_DETAILS",
    "request": "CATALOG_REFERENCES",
}.items() for code in codes.split()})
TABLE_CATALOG = {"PARTS_USED": "REPAIR_PROTOCOL", "REPAIR_EVENTS": "REPAIR_PROTOCOL",
                 "REQUEST_LINES": "PART_REQUEST", "REPAIR_PARTICIPANTS": "REPAIR_PROTOCOL",
                 "REPAIR_ATTACHMENTS": "REPAIR_PROTOCOL", "EQUIPMENT_CHECKLIST": ("TRANSFER_ISSUE", "TRANSFER_RETURN")}
TABLE_COLUMNS = {
    "REQUEST_LINES": {"position", "part_number", "description", "quantity", "unit", "note", "assembly"},
    "PARTS_USED": {"position", "part_number", "description", "quantity", "unit"},
    "REPAIR_EVENTS": {"date", "event_type", "description"},
    "EQUIPMENT_CHECKLIST": {"position", "component", "condition", "measurement", "note"},
    "REPAIR_PARTICIPANTS": {"name", "job_title", "contribution", "duration"},
    "REPAIR_ATTACHMENTS": {"filename", "stage", "description"},
}
PUBLICATION_FIELDS = {
    "TRANSFER_ISSUE": "CREATION_DATE MACHINE_NUMBER SERIAL_NUMBER CONDITION_TEXT REMARKS",
    "TRANSFER_RETURN": "CREATION_DATE MACHINE_NUMBER SERIAL_NUMBER CONDITION_TEXT REMARKS",
    "REPAIR_PROTOCOL": "CREATION_DATE MACHINE_NUMBER REPAIR_REFERENCE REPORTED_PROBLEM CONDITION_BEFORE DIAGNOSTIC_CLEANING REQUIRED_WORK DIAGNOSIS DIAGNOSIS_DURATION WORK_PERFORMED REPAIR_DURATION TESTING_DURATION TEST_RESULT FINAL_RESULT TOTAL_WORK_DURATION PARTICIPANT_TOTAL_DURATION",
    "PART_REQUEST": "CREATION_DATE REMARKS DECISION REQUESTER_NAME APPROVER_NAME APPROVAL_DATE",
}


def publication_fields(document_type: str):
    return PUBLICATION_FIELDS[document_type].split()


def validate_publication_fields(layout, document_type):
    if layout.native is not None:
        from .native_contract import validate
        validate(layout, document_type)
        return
    blocks = list(walk_blocks(layout.blocks))
    actual = {b.field for b in blocks if b.type == "field" and b.region == "body"}
    if not set(publication_fields(document_type)) <= actual:
        raise ValueError("studio_required_block")
    for signature in (b for b in blocks if b.type == "signature" and not b.show_identity):
        side = signature.slot.removesuffix("_SIGNATURE")
        if not {f"{side}_SIGNER_NAME", f"{side}_SIGNER_JOB_TITLE"} <= actual:
            raise ValueError("studio_required_block")
    for source, workflow in TABLE_CATALOG.items():
        # Existing frozen sources still render through check_layout. New
        # publications/activations must include every canonical data source;
        # choosing an older schema number cannot bypass document completeness.
        if document_type in ((workflow,) if isinstance(workflow, str) else workflow) and sum(b.type == "dynamic_table" and b.source == source for b in blocks) != 1:
            raise ValueError("studio_required_block")
    for block in blocks:
        if block.type == "dynamic_table":
            required = {"EQUIPMENT_CHECKLIST": {"component", "condition"}, "REPAIR_PARTICIPANTS": {"name", "duration"},
                "REPAIR_ATTACHMENTS": {"filename"}, "REPAIR_EVENTS": {"description"}}.get(block.source, {"description", "quantity"})
            if not required <= {c.key for c in block.columns}:
                raise ValueError("studio_required_block")


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
    header_mm: float = Field(default=0, ge=0, le=40, allow_inf_nan=False)
    footer_mm: float = Field(default=0, ge=0, le=20, allow_inf_nan=False)
    top_mm: float | None = Field(default=None, ge=0, le=90, allow_inf_nan=False)
    bottom_mm: float | None = Field(default=None, ge=0, le=90, allow_inf_nan=False)
    left_mm: float | None = Field(default=None, ge=0, le=40, allow_inf_nan=False)
    right_mm: float | None = Field(default=None, ge=0, le=40, allow_inf_nan=False)
    header_distance_mm: float | None = Field(default=None, ge=0, le=40, allow_inf_nan=False)
    footer_distance_mm: float | None = Field(default=None, ge=0, le=40, allow_inf_nan=False)


class Style(StrictModel):
    font: Literal["Arial", "Liberation Sans", "DejaVu Sans", "DejaVu Serif", "Times New Roman", "Calibri"] = "Arial"
    size_pt: float = Field(default=11, ge=6, le=48, allow_inf_nan=False)
    color: str = Field(default="#183153", pattern=r"^#[0-9a-fA-F]{6}$")
    align: Literal["left", "center", "right"] = "left"
    spacing_mm: float = Field(default=2, ge=0, le=30, allow_inf_nan=False)
    paragraph_before_mm: float = Field(default=0, ge=0, le=30, allow_inf_nan=False)
    bold: bool = False
    italic: bool = False
    background: str = Field(default="transparent", pattern=r"^(#[0-9a-fA-F]{6}|transparent)$")
    border_pt: float = Field(default=0, ge=0, le=3, allow_inf_nan=False)
    width_percent: float = Field(default=100, ge=10, le=100, allow_inf_nan=False)


class BlockBase(StrictModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    region: Literal["body", "header", "footer"] = "body"
    style: Style = Field(default_factory=Style)


class NativeParagraph(BlockBase):
    type: Literal["native_paragraph"]
    text: str = Field(max_length=10_000)


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
    type: Literal["image", "logo", "native_image"]
    image_id: int | None = Field(default=None, gt=0)
    width_mm: float = Field(default=40, ge=5, le=180, allow_inf_nan=False)
    height_mm: float = Field(default=20, ge=5, le=100, allow_inf_nan=False)

    @model_validator(mode="after")
    def selected_image(self):
        if self.type == "image" and self.image_id is None:
            raise ValueError("studio_image_missing")
        return self


class TableColumn(StrictModel):
    key: Literal["position", "description", "quantity", "unit", "part_number", "note", "date", "event_type",
                 "component", "condition", "measurement", "name", "job_title", "contribution", "duration", "filename", "stage", "assembly"]
    label: str = Field(min_length=1, max_length=100)
    width_percent: float = Field(gt=0, le=100, allow_inf_nan=False)


class DynamicTable(BlockBase):
    type: Literal["dynamic_table"]
    source: Literal["PARTS_USED", "REPAIR_EVENTS", "REQUEST_LINES", "EQUIPMENT_CHECKLIST", "REPAIR_PARTICIPANTS", "REPAIR_ATTACHMENTS"]
    columns: list[TableColumn] = Field(min_length=1, max_length=6)
    repeat_header: Literal[True] = True
    flow: Literal[True] = True
    keep_rows_together: bool = False
    cell_padding_mm: float | None = Field(default=None, ge=0, le=8, allow_inf_nan=False)
    min_height_mm: float | None = Field(default=None, ge=0, le=60, allow_inf_nan=False)
    group_by: Literal["assembly"] | None = None

    @model_validator(mode="after")
    def column_widths(self):
        if self.group_by and self.source != "REQUEST_LINES":
            raise ValueError("studio_incompatible_column")
        if abs(sum(c.width_percent for c in self.columns) - 100) > 0.01:
            raise ValueError("studio_table_width")
        if len({c.key for c in self.columns}) != len(self.columns):
            raise ValueError("studio_duplicate_columns")
        return self


class StaticTable(BlockBase):
    type: Literal["table"]
    rows: list[list[Annotated[str, Field(max_length=2000)]]] = Field(min_length=1, max_length=50)
    widths: list[Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)]] | None = Field(default=None, max_length=8)
    repeat_header: bool = True
    cell_padding_mm: float | None = Field(default=None, ge=0, le=8, allow_inf_nan=False)
    min_height_mm: float | None = Field(default=None, ge=0, le=60, allow_inf_nan=False)

    @model_validator(mode="after")
    def widths_match(self):
        if self.widths is not None and (len(self.widths) != len(self.rows[0]) or any(w < 5 for w in self.widths) or abs(sum(self.widths) - 100) > 0.01):
            raise ValueError("studio_table_width")
        return self

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
    show_identity: bool = True
    label: str = Field(default="", max_length=100)
    min_height_mm: float = Field(default=14, ge=14, le=40, allow_inf_nan=False)


class SystemBlock(BlockBase):
    type: Literal["line", "frame", "page_number", "page_break", "qr"]
    text: str = Field(default="", max_length=2000)
    width_mm: float = Field(default=40, ge=5, le=180, allow_inf_nan=False)
    height_mm: float = Field(default=20, ge=5, le=100, allow_inf_nan=False)


class ConditionalBlock(BlockBase):
    type: Literal["conditional"]
    when_field: str
    text: str = Field(max_length=10_000)

    @field_validator("when_field")
    @classmethod
    def known_field(cls, value):
        return FieldBlock.allowed_field(value)


class GridCell(StrictModel):
    colspan: int = Field(default=1, ge=1, le=8)
    padding_mm: float = Field(default=1.5, ge=0, le=8, allow_inf_nan=False)
    vertical_align: Literal["top", "center", "bottom"] = "top"
    style: Style = Field(default_factory=Style)
    blocks: list["Block"] = Field(default_factory=list, max_length=50)


class GridRow(StrictModel):
    cells: list[GridCell] = Field(min_length=1, max_length=8)
    min_height_mm: float = Field(default=0, ge=0, le=60, allow_inf_nan=False)
    keep_together: bool = False
    page_break_before: bool = False


class GridBlock(BlockBase):
    type: Literal["grid"]
    label: str = Field(default="", max_length=100)
    widths: list[Annotated[float, Field(ge=5, le=100, allow_inf_nan=False)]] = Field(min_length=1, max_length=8)
    grid_rows: list[GridRow] = Field(min_length=1, max_length=50)
    repeat_rows: int = Field(default=0, ge=0, le=3)
    keep_together: bool = False

    @model_validator(mode="after")
    def grid_shape(self):
        if abs(sum(self.widths) - 100) > .01 or self.repeat_rows > len(self.grid_rows):
            raise ValueError("studio_table_width")
        for row in self.grid_rows:
            if sum(c.colspan for c in row.cells) != len(self.widths):
                raise ValueError("studio_table_shape")
            if any(b.region != "body" or b.type == "page_break" for c in row.cells for b in c.blocks):
                raise ValueError("studio_invalid_region")
        return self


Block = Annotated[NativeParagraph | TextBlock | FieldBlock | ImageBlock | DynamicTable | StaticTable
                  | SignatureBlock | SystemBlock | ConditionalBlock | GridBlock, Field(discriminator="type")]
GridCell.model_rebuild()
GridRow.model_rebuild()
GridBlock.model_rebuild()


def walk_blocks(blocks):
    for block in blocks:
        yield block
        if block.type == "grid":
            for row in block.grid_rows:
                for cell in row.cells:
                    yield from walk_blocks(cell.blocks)


class Layout(StrictModel):
    schema_version: Literal[1, 2, 3, 4] = 1
    page: Page = Field(default_factory=Page)
    # Flow is authoritative in v1. Fixed placement is intentionally not yet
    # supported: long text/tables cannot overlap signature areas.
    positioning: Literal["flow"] = "flow"
    blocks: list[Block] = Field(max_length=200)
    # Controlled native sources are frozen with the layout, never fetched by a
    # renderer. Only the conversion endpoint can establish this provenance.
    native: dict | None = None

    @field_validator("native")
    @classmethod
    def bounded_native(cls, value):
        if value is None:
            return value
        if (set(value) != {"adapter", "document_type", "language", "source_version_id", "source_version",
                "source_sha256", "sources", "source_hashes"}
                or type(value["adapter"]) is not int or value["adapter"] != 1
                or value["document_type"] not in SUPPORTED_TYPES or value["language"] not in {"bg", "en", "ru"}
                or any(type(value[k]) is not int or value[k] < 1 for k in ("source_version_id", "source_version"))
                or not isinstance(value["source_sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", value["source_sha256"])
                or not isinstance(value["sources"], dict) or not 1 <= len(value["sources"]) <= 2
                or not isinstance(value["source_hashes"], dict) or set(value["sources"]) != set(value["source_hashes"])
                or any(k not in {"DEFAULT", "MACHINE", "FREE_FORM"} or not isinstance(v, str) or not 1 <= len(v) <= 4_000_000 for k, v in value["sources"].items())
                or any(not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v) for v in value["source_hashes"].values())):
            raise ValueError("studio_native_incompatible")
        return value

    @model_validator(mode="before")
    @classmethod
    def bounded_tree(cls, value):
        if not isinstance(value, dict):
            return value
        count, seen, nodes = 0, set(), 0
        def inspect(blocks, depth):
            nonlocal count, nodes
            if depth > 4 or not isinstance(blocks, list):
                raise ValueError("studio_layout_size")
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                count += 1
                if count > 200 or id(b) in seen:
                    raise ValueError("studio_layout_size")
                seen.add(id(b))
                if b.get("type") == "grid":
                    rows = b.get("grid_rows", [])
                    if not isinstance(rows, list) or len(rows) > 50:
                        raise ValueError("studio_table_shape")
                    for row in rows:
                        if not isinstance(row, dict) or not isinstance(row.get("cells", []), list) or len(row.get("cells", [])) > 8:
                            raise ValueError("studio_table_shape")
                        for cell in row.get("cells", []):
                            nodes += 1
                            if not isinstance(cell, dict) or nodes > 800:
                                raise ValueError("studio_layout_size")
                            inspect(cell.get("blocks", []), depth + 1)
        inspect(value.get("blocks", []), 0)
        return value

    @model_validator(mode="after")
    def identifiers(self):
        blocks = list(walk_blocks(self.blocks))
        if len({b.id for b in blocks}) != len(blocks):
            raise ValueError("studio_duplicate_block_ids")
        if any(b.region != "body" and b.type in {"dynamic_table", "signature", "page_break"}
               for b in self.blocks):
            raise ValueError("studio_invalid_region")
        if sum(len(str(b.model_dump())) for b in self.blocks) > 160_000:
            raise ValueError("studio_layout_size")
        return self


class DraftCreate(StrictModel):
    title: str = Field(min_length=1, max_length=255)
    language: Literal["bg", "en", "ru"] = "bg"
    base_version_id: int | None = Field(default=None, gt=0)
    design: Literal["professional", "blank"] = "professional"


class DraftUpdate(StrictModel):
    expected_revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=255)
    layout: Layout


class PreviewInput(StrictModel):
    expected_revision: int = Field(ge=1)
    rows: Literal[1, 5, 30] = 5
    request_variant: Literal["MACHINE", "FREE_FORM"] = "MACHINE"


class PublishInput(PreviewInput):
    change_note: str = Field(min_length=3, max_length=2000)
    receipt: str = Field(min_length=40, max_length=2000)


class ActivationInput(StrictModel):
    expected_version_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=3, max_length=2000)
    expected_revision: int | None = Field(default=None, ge=0)


class RestoreInput(ActivationInput):
    expected_revision: int = Field(ge=1)
    confirmed: Literal[True]


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
    if layout.native is not None:
        from .native_contract import validate
        validate(layout, document_type)
        return
    if any(b.type in {"native_paragraph", "native_image"} for b in walk_blocks(layout.blocks)):
        raise ValueError("studio_native_incompatible")
    required = initial_layout(document_type)
    blocks = list(walk_blocks(layout.blocks))
    for block in required.blocks:
        if sum(b.type == block.type and (
            getattr(b, "field", None) == getattr(block, "field", None)
            and getattr(b, "slot", None) == getattr(block, "slot", None)
        ) for b in blocks) != 1:
            raise ValueError("studio_required_block")
    for block in blocks:
        workflow = TABLE_CATALOG.get(getattr(block, "source", None))
        if isinstance(block, DynamicTable) and document_type not in ((workflow,) if isinstance(workflow, str) else workflow):
            raise ValueError("studio_incompatible_table")
        if isinstance(block, DynamicTable) and any(c.key not in TABLE_COLUMNS[block.source] for c in block.columns):
            raise ValueError("studio_incompatible_column")
        field = block.field if isinstance(block, FieldBlock) else block.when_field if isinstance(block, ConditionalBlock) else None
        if field:
            group = FIELD_CATALOG[field]
            if ((group == "repair" and document_type != "REPAIR_PROTOCOL")
                    or (group == "transfer" and document_type not in {"TRANSFER_ISSUE", "TRANSFER_RETURN"})
                    or (group == "request" and document_type != "PART_REQUEST")
                    or (field == "REMARKS" and document_type == "REPAIR_PROTOCOL")):
                raise ValueError("studio_incompatible_field")
