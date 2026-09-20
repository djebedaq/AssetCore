"""Version 1 read-only contract for historical visual evidence."""

from typing import Literal

from pydantic import BaseModel


class CapturedCatalog(BaseModel):
    source_row_index: int | None
    source_version: str | None
    source_document_sha256: str | None
    revision: str | None
    verification_status: str
    is_verified: bool
    verified_by_id: int | None
    verified_at: str | None
    position: str | None
    part_number: str
    replaced_by_part_number: str | None
    requested_part_number: str
    description: str
    original_name: str | None
    manufacturer: str | None
    brand: str
    model: str | None
    family: str | None
    assembly: str | None
    unit: str | None
    source_document: str | None
    source_page: int | None
    source_figure: str | None
    diagram_page: int | None


class CapturedVisualSource(BaseModel):
    document_title: str
    document_source_id: str | None
    document_dataset_version: str | None
    document_revision: str | None
    document_sha256: str | None
    revision_id: int | None
    revision_version: int | None
    revision_label: str | None
    filename: str | None
    media_type: str
    byte_length: int
    hotspot_key: str | None
    label: str | None
    provenance: str | None
    confidence: float | None
    is_verified: bool
    verified_by_id: int | None
    verified_at: str | None
    diagram_title: str | None
    diagram_source_id: str | None
    diagram_source_sha256: str | None
    render_version: str | None


class CapturedVisualOccurrence(BaseModel):
    ordinal: int
    source_kind: Literal["PART_HOTSPOT", "POSITION_HOTSPOT"]
    hotspot_id: int
    technical_document_id: int
    diagram_id: int | None
    page_number: int
    x: float
    y: float
    width: float
    height: float
    artifact_sha256: str
    source_metadata: CapturedVisualSource


class VisualSnapshotOut(BaseModel):
    id: int
    sha256: str
    schema_version: Literal[1]
    line_id: int
    catalog_part_id: int
    source_id: str | None
    source_record_key: str | None
    captured_at: str
    capture_origin: Literal["REQUEST_CREATION", "CATALOG_LINK"]
    catalog: CapturedCatalog
    occurrence_count: int
    visual_references: list[CapturedVisualOccurrence]


class VisualReferenceOut(BaseModel):
    state: Literal[
        "verified_visual_references",
        "no_visual_reference_at_capture",
        "legacy_snapshot_unavailable",
        "no_catalog_binding",
    ]
    snapshot: VisualSnapshotOut | None
