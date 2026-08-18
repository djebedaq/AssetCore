from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    CatalogDiagram,
    CatalogPositionHotspot,
    PartCatalog,
    RepairKit,
    RepairKitComponent,
)
from .sources import CATALOG_VERSION


def active_parts_statement():
    return select(PartCatalog).where(
        PartCatalog.is_active.is_(True),
        PartCatalog.is_verified.is_(True),
        PartCatalog.source_version == CATALOG_VERSION,
    )


def parts_for_source(db: Session, source_id: str) -> list[PartCatalog]:
    return list(
        db.scalars(
            active_parts_statement()
            .where(PartCatalog.source_id == source_id)
            .order_by(
                PartCatalog.source_page,
                PartCatalog.source_row_index,
                PartCatalog.id,
            )
        )
    )


def search_parts(
    db: Session,
    *,
    query: str,
    family: str,
    source_id: str | None = None,
    limit: int = 100,
) -> list[PartCatalog]:
    statement = active_parts_statement().where(PartCatalog.family == family)
    if source_id:
        statement = statement.where(PartCatalog.source_id == source_id)
    if query.strip():
        term = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                PartCatalog.part_number.ilike(term),
                PartCatalog.replaced_by_part_number.ilike(term),
                PartCatalog.position.ilike(term),
                PartCatalog.description.ilike(term),
                PartCatalog.description_de.ilike(term),
                PartCatalog.description_en.ilike(term),
                PartCatalog.description_2.ilike(term),
                PartCatalog.assembly.ilike(term),
                PartCatalog.model.ilike(term),
                PartCatalog.repair_kit_code.ilike(term),
                PartCatalog.valid_for_raw.ilike(term),
            )
        )
    return list(
        db.scalars(
            statement.order_by(
                PartCatalog.assembly,
                PartCatalog.position,
                PartCatalog.source_row_index,
            ).limit(limit)
        )
    )


def diagrams_for_source(db: Session, source_id: str) -> list[CatalogDiagram]:
    return list(
        db.scalars(
            select(CatalogDiagram)
            .where(CatalogDiagram.source_id == source_id)
            .order_by(CatalogDiagram.page_number)
        )
    )


def verified_hotspot_count(db: Session, source_id: str) -> int:
    return int(
        db.scalar(
            select(func.count(CatalogPositionHotspot.id))
            .join(CatalogDiagram)
            .where(
                CatalogDiagram.source_id == source_id,
                CatalogPositionHotspot.is_verified.is_(True),
            )
        )
        or 0
    )


def hotspots_for_diagram(
    db: Session, diagram_id: int, *, verified_only: bool
) -> list[CatalogPositionHotspot]:
    statement = select(CatalogPositionHotspot).where(
        CatalogPositionHotspot.diagram_id == diagram_id
    )
    if verified_only:
        statement = statement.where(CatalogPositionHotspot.is_verified.is_(True))
    return list(
        db.scalars(statement.order_by(CatalogPositionHotspot.position, CatalogPositionHotspot.id))
    )


def repair_kits(
    db: Session, *, family: str, source_id: str | None = None
) -> list[RepairKit]:
    statement = (
        select(RepairKit)
        .options(selectinload(RepairKit.components).joinedload(RepairKitComponent.part))
        .where(
            RepairKit.family == family,
            RepairKit.source_version == CATALOG_VERSION,
            RepairKit.is_active.is_(True),
            RepairKit.is_approved.is_(True),
        )
    )
    if source_id:
        statement = statement.where(RepairKit.source_id == source_id)
    return list(db.scalars(statement.order_by(RepairKit.code)))
