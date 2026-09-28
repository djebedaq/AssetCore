"""Read projections for Builder screens; counts are fetched without N+1 queries."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AssetCategory, CatalogAssetBinding, CatalogDefinition, CatalogRevision, Machine


def catalogs(db: Session) -> list[dict]:
    bindings = (select(CatalogAssetBinding.catalog_id, func.count().label("n"))
                .group_by(CatalogAssetBinding.catalog_id).subquery())
    drafts = (select(CatalogRevision.catalog_id, func.count().label("n"))
              .where(CatalogRevision.status == "DRAFT")
              .group_by(CatalogRevision.catalog_id).subquery())
    rows = db.execute(
        select(CatalogDefinition, AssetCategory, func.coalesce(bindings.c.n, 0),
               func.coalesce(drafts.c.n, 0))
        .join(AssetCategory, AssetCategory.id == CatalogDefinition.asset_category_id)
        .outerjoin(bindings, bindings.c.catalog_id == CatalogDefinition.id)
        .outerjoin(drafts, drafts.c.catalog_id == CatalogDefinition.id)
        .order_by(CatalogDefinition.code)
    ).all()
    # Revision identifiers for all catalogs in one additional query.
    revisions = db.execute(select(CatalogRevision.catalog_id, CatalogRevision.id,
                                  CatalogRevision.revision_code, CatalogRevision.status)
                           .order_by(CatalogRevision.catalog_id, CatalogRevision.created_at.desc(),
                                     CatalogRevision.id.desc())).all()
    latest, published = {}, {}
    for catalog_id, revision_id, code, status in revisions:
        latest.setdefault(catalog_id, {"id": revision_id, "revision_code": code})
        if status == "PUBLISHED":
            published.setdefault(catalog_id, {"id": revision_id, "revision_code": code})
    return [{
        "id": item.id, "code": item.code, "name_bg": item.name_bg,
        "name_en": item.name_en, "name_ru": item.name_ru,
        "description": item.description, "manufacturer": item.manufacturer,
        "model_reference": item.model_reference, "is_active": item.is_active,
        "asset_category_id": category.id, "asset_category": {
            "id": category.id, "code": category.code, "name_bg": category.name_bg,
            "name_en": category.name_en, "name_ru": category.name_ru,
        },
        "bound_asset_count": bound_count, "draft_revision_count": draft_count,
        "latest_revision": latest.get(item.id), "published_revision": published.get(item.id),
        "created_at": item.created_at, "updated_at": item.updated_at,
    } for item, category, bound_count, draft_count in rows]


def assets(db: Session, catalog_id: int) -> list[dict]:
    rows = db.scalars(select(Machine).join(CatalogAssetBinding,
                                            CatalogAssetBinding.machine_id == Machine.id)
                      .where(CatalogAssetBinding.catalog_id == catalog_id)
                      .order_by(Machine.inventory_number)).all()
    return [asset_dict(item) for item in rows]


def asset_dict(item: Machine) -> dict:
    return {"id": item.id, "inventory_number": item.inventory_number,
            "name": item.name, "brand": item.brand, "model": item.model,
            "category_id": item.category_id, "is_active": item.is_active}
