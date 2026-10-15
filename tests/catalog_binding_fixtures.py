"""Explicit pre-UX06 database fixtures. Never a production/API write path.

Used only by pending-publication/history/migration regression scenarios. New
binding behavior is tested through the real service and HTTP API elsewhere.
"""

from app.audit import add_audit_log
from app.models import CatalogAssetBinding, User
from sqlalchemy import select


def legacy_binding(db, actor, catalog_id, machine_id):
    row = db.scalar(select(CatalogAssetBinding).where(CatalogAssetBinding.catalog_id == catalog_id,
                                                      CatalogAssetBinding.machine_id == machine_id))
    row = row or CatalogAssetBinding(catalog_id=catalog_id, machine_id=machine_id, created_by_id=actor.id)
    row.is_active, row.deactivated_at = True, None
    db.add(row)
    db.flush()
    add_audit_log(db, actor, "catalog_asset_binding", row.id, "CATALOG_ASSET_BOUND",
                  {"catalog_id": catalog_id, "machine_id": machine_id, "fixture": "PRE_UX06_PENDING"})
    db.commit()
    return row.id


def legacy_pending(factory, catalog_id, machine_id):
    with factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        return legacy_binding(db, actor, catalog_id, machine_id)
