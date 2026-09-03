from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class OfficialRegistryFileOut(BaseModel):
    format: Literal["docx", "pdf"]
    download_endpoint: str
    preview_endpoint: str | None = None


class OfficialRegistryDocumentOut(BaseModel):
    document_type: str
    document_number: str
    official_document_id: int | None = None
    version: int | None = None
    version_status: str | None = None
    files: list[OfficialRegistryFileOut] = Field(default_factory=list)


class OfficialRegistryItemOut(BaseModel):
    registry_key: str
    domain_id: int | None = None
    machine_id: int | None = None
    machine_number: str | None = None
    status: str
    signature_status: Literal[
        "SIGNED", "PARTIALLY_SIGNED", "UNSIGNED", "NOT_REQUIRED", "UNKNOWN"
    ]
    created_at: datetime | None = None
    started_at: datetime | None = None
    documents: list[OfficialRegistryDocumentOut] = Field(default_factory=list)


class OfficialRegistrySectionOut(BaseModel):
    count: int
    items: list[OfficialRegistryItemOut] = Field(default_factory=list)


class OfficialDocumentRegistryOut(BaseModel):
    transfers: OfficialRegistrySectionOut
    repairs: OfficialRegistrySectionOut
    parts: OfficialRegistrySectionOut


class OfficialRegistryCategory(str, Enum):
    TRANSFERS = "transfers"
    REPAIRS = "repairs"
    PARTS = "parts"


class OfficialRegistryPageOut(BaseModel):
    category: OfficialRegistryCategory
    total: int = Field(ge=0)
    count: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total_pages: int = Field(ge=0)
    has_previous: bool
    has_next: bool
    items: list[OfficialRegistryItemOut] = Field(default_factory=list)


class OfficialRegistryCountsOut(BaseModel):
    transfers: int = Field(ge=0)
    repairs: int = Field(ge=0)
    parts: int = Field(ge=0)
