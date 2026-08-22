from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class CatalogPartOut(BaseModel):
    id: int
    source_record_key: str
    source_id: str
    source_row_index: int
    family: str
    brand: str
    model: str
    assembly: str
    position: str
    part_number: str
    order_part_number: str
    replaced_by_part_number: str | None = None
    description: str
    source_description: str
    description_en: str
    description_bg: str
    original_name: str | None = None
    description_2: str | None = None
    quantity: float | None = None
    quantity_raw: str
    valid_for_raw: str | None = None
    repair_kit_code: str | None = None
    source_document: str
    source_page: int
    source_figure: str | None = None
    source_version: str
    source_document_sha256: str
    verification_status: str
    source_anomaly_codes: list[str] = Field(default_factory=list)
    is_verified: bool
    translation_version: str
    translation_qa_status: str


class CatalogDiagramOut(BaseModel):
    id: int
    source_id: str
    page_number: int
    title: str
    source_pdf_sha256: str
    render_version: str
    technical_document_id: int
    preview_endpoint: str
    download_endpoint: str


class CatalogAssemblyOut(BaseModel):
    source_id: str
    family: str
    assembly: str
    title: str
    document_reference: str | None = None
    part_count: int
    diagram_count: int
    verified_hotspot_count: int
    diagrams: list[CatalogDiagramOut]


class MachineCatalogOut(BaseModel):
    dataset_version: str
    supported: bool
    message: str
    machine_id: int
    machine_number: str
    brand: str | None = None
    model: str | None = None
    family: str | None = None
    assemblies: list[CatalogAssemblyOut] = Field(default_factory=list)


class AssemblyDetailsOut(BaseModel):
    dataset_version: str
    machine_id: int
    machine_number: str
    family: str
    source_id: str
    assembly: str
    title: str
    diagrams: list[CatalogDiagramOut]
    parts: list[CatalogPartOut]


class PositionHotspotOut(BaseModel):
    id: int
    hotspot_key: str
    diagram_id: int
    page_number: int
    position: str
    x: float
    y: float
    width: float
    height: float
    is_verified: bool
    provenance: str
    confidence: float | None = None
    verified_at: datetime | None = None
    variants: list[CatalogPartOut]


class RepairKitComponentOut(BaseModel):
    id: int
    part_id: int
    source_record_key: str
    position: str
    part_number: str
    description: str
    source_description: str
    description_en: str
    description_bg: str
    quantity: float
    quantity_raw: str
    source_document: str
    source_page: int
    translation_version: str
    translation_qa_status: str


class RepairKitOut(BaseModel):
    id: int
    code: str
    name: str
    family: str
    source_id: str
    brand: str
    model: str
    assembly: str
    source_document: str
    source_page: int
    source_document_sha256: str
    source_version: str
    is_approved: bool
    is_active: bool
    components: list[RepairKitComponentOut]


class HotspotUpdate(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)
    is_verified: bool
    reason: str = Field(min_length=5, max_length=1000)

    @model_validator(mode="after")
    def geometry_stays_on_page(self) -> "HotspotUpdate":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("Областта трябва да остане изцяло в границите на схемата.")
        return self


class HotspotUpdateOut(BaseModel):
    id: int
    is_verified: bool
    verified_at: datetime | None = None
    x: float
    y: float
    width: float
    height: float
    provenance: str
    confidence: float | None = None


class PositionMappingCoverageOut(BaseModel):
    review_version: str
    reviewed_diagram_page_count: int
    sources: list[dict]
    totals: dict
