"""Read-only lifecycle contract; codes are translated by future consumers."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class TimelineCategory(str, Enum):
    ALL = "all"
    ASSET = "asset"
    TRANSFER = "transfer"
    REPAIR = "repair"
    PARTS = "parts"
    DOCUMENT = "document"


class TimelineRelated(BaseModel):
    transfer_id: int | None = None
    repair_id: int | None = None
    part_request_id: int | None = None
    official_document_id: int | None = None


class MachineTimelineItem(BaseModel):
    event_key: str
    category: TimelineCategory
    event_type: str
    occurred_at: datetime
    reference: str | None = None
    source_type: str
    source_id: int
    status_before: str | None = None
    status_after: str | None = None
    description: str | None = None
    machine_id: int
    related: TimelineRelated = Field(default_factory=TimelineRelated)
    # Only explicit per-event projections populate this field, never raw JSON.
    details: dict[str, str | int | float | bool | None | list[str | int]] = Field(
        default_factory=dict
    )


class MachineTimelinePage(BaseModel):
    machine_id: int
    limited_view: bool
    category: TimelineCategory
    total: int
    count: int
    page: int
    page_size: int
    total_pages: int
    has_previous: bool
    has_next: bool
    items: list[MachineTimelineItem]
