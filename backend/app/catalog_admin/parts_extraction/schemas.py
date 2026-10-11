"""Small preview/confirm contracts; clients never supply authoritative evidence."""

from typing import Literal

from pydantic import Field

from ..schemas import PartCreate, Payload


class PageCreate(Payload):
    title: str | None = Field(default=None, max_length=255)


class PageUpdate(PageCreate):
    expected_version: int = Field(ge=1)
    sort_order: int | None = Field(default=None, ge=0)


class SourceAssign(Payload):
    expected_version: int = Field(ge=1)
    artifact_id: int = Field(gt=0)
    page_numbers: list[int] = Field(min_length=1, max_length=100)
    roles: list[Literal["EXPLODED_SCHEME", "SPARE_PARTS_LIST"]] = Field(min_length=1, max_length=2)


class ExtractSelection(Payload):
    visual_page_id: int = Field(gt=0)
    continuation_token: str | None = Field(default=None, max_length=4_000_000)


class ColumnMapping(Payload):
    token: str = Field(min_length=1, max_length=4_000_000)
    table_index: int = Field(ge=0, le=79)
    mapping: dict[str, Literal["unknown", "position", "part_number", "description", "quantity",
                             "technical_notes", "technical_specification"]] = Field(max_length=12)


class ConfirmRow(Payload):
    index: int = Field(ge=0, le=1999)
    part: PartCreate
    expected_version: int | None = Field(default=None, ge=1)


class ExtractConfirm(Payload):
    token: str = Field(min_length=1, max_length=4_000_000)
    rows: list[ConfirmRow] = Field(min_length=1, max_length=1000)
    confirm_warnings: bool = False


class CandidateEdit(Payload):
    expected_version: int = Field(ge=1)
    values: dict[str, str | int | float | None] | None = Field(default=None, max_length=24)
    action: Literal["SAVE", "REJECT", "RESTORE", "LINK_EXISTING", "NEW_VARIANT"] = "SAVE"
    part_id: int | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, min_length=10, max_length=2000)


class SourceReview(Payload):
    expected_version: int = Field(ge=1)
    fingerprint: str = Field(min_length=64, max_length=64)
    inspection_token: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=10, max_length=2000)
    manual_transcription: bool = False


class PageOrderItem(Payload):
    id: int = Field(gt=0)
    expected_version: int = Field(ge=1)


class PageOrder(Payload):
    pages: list[PageOrderItem] = Field(min_length=1, max_length=1000)


class ReferenceOrder(Payload):
    expected_ids: list[int] = Field(min_length=1, max_length=1000)
    ordered_ids: list[int] = Field(min_length=1, max_length=1000)


class SourceOrder(Payload):
    expected_version: int = Field(ge=1)
    ordered_ids: list[int] = Field(min_length=1, max_length=2000)
