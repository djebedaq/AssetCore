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

_UNSELECTED = object()


@dataclass(frozen=True)
class PublishedBinding:
    catalog_id: int
    revision_id: int


def published_binding(db: Session, machine: Machine, *, lock: bool = False) -> PublishedBinding | None:
    if lock and db.get_bind().dialect.name == "postgresql":
        # Binding changes lock the machine before the catalog. Hold a shared
        # lock in the same order, including the currently unbound case.
        db.scalar(select(Machine).where(Machine.id == machine.id)
                  .with_for_update(read=True).execution_options(populate_existing=True))
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
                            *, selected: PublishedBinding | None | object = _UNSELECTED,
                            incompatible_code: str = "catalog_parts_not_compatible_with_machine") -> None:
    binding = (published_binding(db, machine, lock=True) if machine else None) if selected is _UNSELECTED else selected
    from .references import permits_part

    if permits_part(db, machine, part):
        return
    if part.builder_revision_id is not None:
        if binding is None or binding.revision_id != part.builder_revision_id:
            raise business_conflict("catalog_runtime_binding_mismatch",
                                    "Частта не принадлежи към текущия каталог на машината.")
    elif binding is not None:
        raise business_conflict("catalog_runtime_binding_mismatch",
                                "Частта не принадлежи към текущия каталог на машината.")
    elif machine is not None and not _legacy_compatible(machine, part):
        raise business_conflict(incompatible_code,
                                "Каталожната част не е потвърдена за тази машина.")


def _legacy_compatible(machine, part):
    from ..machine_identity import legacy_catalog_number, verified_family
    from .sources import CATALOG_VERSION

    if part.source_version != CATALOG_VERSION:
        return str(machine.inventory_number) in {str(value) for value in (part.compatible_machine_numbers or [])}
    if part.family == "FALCH_500" and verified_family(machine) != "FALCH_500":
        return False
    return (machine.brand == part.brand and machine.model == part.model
            and legacy_catalog_number(machine) in {
            str(value) for value in (part.compatible_machine_numbers or [])}
            )


def require_compatible_kit(db: Session, machine: Machine | None, kit: RepairKit,
                           *, selected: PublishedBinding | None | object = _UNSELECTED) -> None:
    binding = (published_binding(db, machine, lock=True) if machine else None) if selected is _UNSELECTED else selected
    if kit.builder_revision_id is not None:
        if binding is None or binding.revision_id != kit.builder_revision_id:
            raise business_conflict("catalog_runtime_binding_mismatch",
                                    "Комплектът не принадлежи към текущия каталог на машината.")
    elif binding is not None:
        raise business_conflict("catalog_runtime_binding_mismatch",
                                "Комплектът не принадлежи към текущия каталог на машината.")
    elif machine is not None:
        from .service import machine_family
        from .sources import CATALOG_VERSION

        # Individual part approvals do not approve an entire foreign kit.
        if kit.source_version == CATALOG_VERSION and machine_family(machine) != kit.family:
            raise business_conflict("catalog_parts_not_compatible_with_machine",
                                    "Ремонтният комплект не е потвърден за тази машина.")
        # KIT mode has no selected catalog lines. Its components still carry
        # the verified legacy compatibility, which must be checked here too.
        for component in kit.components:
            require_compatible_part(db, machine, component.part, selected=None)
