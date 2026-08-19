from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..application_errors import ApplicationError
from ..audit import add_audit_log
from ..database import get_db
from ..models import CatalogPositionHotspot, User, utcnow
from ..permissions import Permission, ensure_permission, require_permission
from . import service
from .position_mapping import MANUALLY_CONFIRMED
from .schemas import (
    AssemblyDetailsOut,
    CatalogPartOut,
    HotspotUpdate,
    HotspotUpdateOut,
    MachineCatalogOut,
    PositionHotspotOut,
    PositionMappingCoverageOut,
    RepairKitOut,
)

router = APIRouter(prefix="/api/catalog/v2", tags=["authoritative-parts-catalog"])
require_catalog_viewer = require_permission(Permission.PARTS_VIEW)
require_catalog_manager = require_permission(Permission.PARTS_MANAGE)


@router.get("/machines/{machine_id}", response_model=MachineCatalogOut)
def get_machine_catalog(
    machine_id: int,
    _: User = Depends(require_catalog_viewer),
    db: Session = Depends(get_db),
) -> dict:
    return service.machine_catalog(db, machine_id)


@router.get("/assemblies/{source_id}", response_model=AssemblyDetailsOut)
def get_assembly(
    source_id: str,
    machine_id: int = Query(gt=0),
    _: User = Depends(require_catalog_viewer),
    db: Session = Depends(get_db),
) -> dict:
    return service.assembly_details(db, machine_id=machine_id, source_id=source_id)


@router.get("/search", response_model=list[CatalogPartOut])
def search_catalog(
    machine_id: int = Query(gt=0),
    q: str = Query(default="", max_length=200),
    source_id: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=100, ge=1, le=300),
    _: User = Depends(require_catalog_viewer),
    db: Session = Depends(get_db),
) -> list[dict]:
    return service.search(
        db,
        machine_id=machine_id,
        query=q,
        source_id=source_id,
        limit=limit,
    )


@router.get(
    "/diagrams/{diagram_id}/hotspots", response_model=list[PositionHotspotOut]
)
def get_diagram_hotspots(
    diagram_id: int,
    machine_id: int = Query(gt=0),
    verified_only: bool = True,
    user: User = Depends(require_catalog_viewer),
    db: Session = Depends(get_db),
) -> list[dict]:
    if not verified_only:
        ensure_permission(user, Permission.PARTS_MANAGE)
    return service.diagram_hotspots(
        db,
        diagram_id=diagram_id,
        machine_id=machine_id,
        verified_only=verified_only,
    )


@router.get("/position-mapping/coverage", response_model=PositionMappingCoverageOut)
def get_position_mapping_coverage(
    _: User = Depends(require_catalog_manager),
) -> dict:
    return service.mapping_coverage()


@router.get("/repair-kits", response_model=list[RepairKitOut])
def get_repair_kits(
    machine_id: int = Query(gt=0),
    source_id: str | None = Query(default=None, max_length=120),
    _: User = Depends(require_catalog_viewer),
    db: Session = Depends(get_db),
) -> list[dict]:
    return service.kits(db, machine_id=machine_id, source_id=source_id)


@router.get("/repair-kits/{kit_id}", response_model=RepairKitOut)
def get_repair_kit(
    kit_id: int,
    machine_id: int = Query(gt=0),
    _: User = Depends(require_catalog_viewer),
    db: Session = Depends(get_db),
) -> dict:
    return service.kit_details(db, machine_id=machine_id, kit_id=kit_id)


@router.patch("/hotspots/{hotspot_id}", response_model=HotspotUpdateOut)
def update_hotspot(
    hotspot_id: int,
    payload: HotspotUpdate,
    user: User = Depends(require_catalog_manager),
    db: Session = Depends(get_db),
) -> dict:
    hotspot = db.get(CatalogPositionHotspot, hotspot_id)
    if hotspot is None:
        raise ApplicationError(
            status_code=404,
            code="catalog_hotspot_not_found",
            message="Визуалната позиция не е намерена.",
            operation="catalog_hotspot_update",
            stage="lookup",
        )
    service.ensure_integrity(hotspot.diagram.source_id)
    before = {
        "x": hotspot.x,
        "y": hotspot.y,
        "width": hotspot.width,
        "height": hotspot.height,
        "is_verified": hotspot.is_verified,
        "provenance": hotspot.provenance,
        "confidence": hotspot.confidence,
    }
    hotspot.x = payload.x
    hotspot.y = payload.y
    hotspot.width = payload.width
    hotspot.height = payload.height
    hotspot.is_verified = payload.is_verified
    hotspot.verified_by_id = user.id if payload.is_verified else None
    hotspot.verified_at = utcnow() if payload.is_verified else None
    hotspot.provenance = MANUALLY_CONFIRMED
    hotspot.confidence = 1.0
    after = {
        **payload.model_dump(exclude={"reason"}),
        "provenance": hotspot.provenance,
        "confidence": hotspot.confidence,
    }
    add_audit_log(
        db,
        user,
        "catalog_position_hotspot",
        hotspot.id,
        "Коригирана и проверена визуална позиция в каталога",
        {
            "hotspot_key": hotspot.hotspot_key,
            "position": hotspot.position,
            "source_id": hotspot.diagram.source_id,
            "source_page": hotspot.diagram.page_number,
            "before": before,
            "after": after,
            "reason": payload.reason,
        },
        hotspot.hotspot_key,
    )
    db.commit()
    db.refresh(hotspot)
    return {
        "id": hotspot.id,
        "is_verified": hotspot.is_verified,
        "verified_at": hotspot.verified_at,
        "x": hotspot.x,
        "y": hotspot.y,
        "width": hotspot.width,
        "height": hotspot.height,
        "provenance": hotspot.provenance,
        "confidence": hotspot.confidence,
    }
