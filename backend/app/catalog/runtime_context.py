"""Explicit Builder binding and current-publication selection."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    CatalogAssetBinding,
    CatalogDefinition,
    CatalogRevision,
    Machine,
    PartCatalog,
    RepairKit,
)
from ..workflow import business_conflict


@dataclass(frozen=True)
class PublishedBinding:
    catalog_id: int
    revision_id: int


def published_binding(db: Session, machine: Machine, *, lock: bool = False) -> PublishedBinding | None:
    binding = db.scalar(select(CatalogAssetBinding).where(CatalogAssetBinding.machine_id == machine.id))
    if binding is None:
        return None
    statement = select(CatalogDefinition).where(CatalogDefinition.id == binding.catalog_id)
    if lock and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(read=True)
    catalog = db.scalar(statement.execution_options(populate_existing=True))
    if catalog is None or not catalog.is_active or catalog.asset_category_id != machine.category_id:
        return None
    revision = db.scalar(select(CatalogRevision).where(CatalogRevision.catalog_id == catalog.id,
                                                        CatalogRevision.status == "PUBLISHED"))
    return PublishedBinding(catalog.id, revision.id) if revision else None


def require_compatible_part(db: Session, machine: Machine | None, part: PartCatalog,
                            *, selected: PublishedBinding | None = None,
                            incompatible_code: str = "catalog_parts_not_compatible_with_machine") -> None:
    binding = selected if selected is not None else published_binding(db, machine, lock=True) if machine else None
    if part.builder_revision_id is not None:
        if binding is None or binding.revision_id != part.builder_revision_id:
            raise business_conflict("catalog_runtime_binding_mismatch",
                                    "Частта не принадлежи към текущия каталог на машината.")
    elif binding is not None:
        raise business_conflict("catalog_runtime_binding_mismatch",
                                "Частта не принадлежи към текущия каталог на машината.")
    elif machine is not None and str(machine.inventory_number) not in {
            str(value) for value in (part.compatible_machine_numbers or [])}:
        raise business_conflict(incompatible_code,
                                "Каталожната част не е потвърдена за тази машина.")


def require_compatible_kit(db: Session, machine: Machine | None, kit: RepairKit,
                           *, selected: PublishedBinding | None = None) -> None:
    binding = selected if selected is not None else published_binding(db, machine, lock=True) if machine else None
    if kit.builder_revision_id is not None:
        if binding is None or binding.revision_id != kit.builder_revision_id:
            raise business_conflict("catalog_runtime_binding_mismatch",
                                    "Комплектът не принадлежи към текущия каталог на машината.")
    elif binding is not None:
        raise business_conflict("catalog_runtime_binding_mismatch",
                                "Комплектът не принадлежи към текущия каталог на машината.")
