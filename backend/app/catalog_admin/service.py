"""Builder write rules. Nothing here reads or writes the controlled runtime catalog."""

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..models import (
    AssetCategory,
    CatalogAssetBinding,
    CatalogDefinition,
    CatalogRevision,
    Machine,
    User,
    utcnow,
)
from . import repository
from .schemas import CatalogCreate, CatalogUpdate, RevisionCreate, RevisionUpdate


def fail(code: str, status: int = 409) -> HTTPException:
    return HTTPException(status, detail={"code": code})


def category_for_builder(db: Session, category_id: int, *, active: bool = True) -> AssetCategory:
    category = db.scalar(select(AssetCategory).where(AssetCategory.id == category_id)
                         .with_for_update().execution_options(populate_existing=True))
    if category is None:
        raise fail("catalog_category_not_found", 404)
    if "HAS_PARTS_CATALOG" not in (category.capabilities or []):
        raise fail("catalog_category_not_supported")
    if active and not category.is_active:
        raise fail("catalog_category_inactive")
    return category


def catalog(db: Session, catalog_id: int, *, lock: bool = False) -> CatalogDefinition:
    query = select(CatalogDefinition).where(CatalogDefinition.id == catalog_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    item = db.scalar(query)
    if item is None:
        raise fail("catalog_definition_not_found", 404)
    return item


def catalog_dict(db: Session, item: CatalogDefinition) -> dict:
    return next(row for row in repository.catalogs(db) if row["id"] == item.id)


def create_catalog(db: Session, actor: User, data: CatalogCreate) -> dict:
    category_for_builder(db, data.asset_category_id)
    item = CatalogDefinition(**data.model_dump(), created_by_id=actor.id)
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise fail("catalog_code_duplicate") from exc
    add_audit_log(db, actor, "catalog_definition", item.id, "CATALOG_CREATED",
                  {"code": item.code, "asset_category_id": item.asset_category_id})
    db.commit()
    return catalog_dict(db, item)


def update_catalog(db: Session, actor: User, catalog_id: int, data: CatalogUpdate) -> dict:
    item = catalog(db, catalog_id, lock=True)
    changes = data.model_dump(exclude_unset=True)
    if "code" in changes:
        raise fail("catalog_code_immutable")
    if any(changes.get(key) is None for key in ("name_bg", "name_en", "name_ru", "is_active", "asset_category_id") if key in changes):
        raise fail("catalog_invalid_update", 422)
    if "asset_category_id" in changes and changes["asset_category_id"] != item.asset_category_id:
        used = db.scalar(select(CatalogRevision.id).where(CatalogRevision.catalog_id == item.id).limit(1))
        bound = db.scalar(select(CatalogAssetBinding.id).where(CatalogAssetBinding.catalog_id == item.id).limit(1))
        if used or bound:
            raise fail("catalog_category_in_use")
        category_for_builder(db, changes["asset_category_id"])
    before = {key: getattr(item, key) for key in changes}
    for key, value in changes.items():
        setattr(item, key, value)
    item.updated_at = utcnow()
    if changes:
        add_audit_log(db, actor, "catalog_definition", item.id,
                      "CATALOG_ACTIVATED" if changes.get("is_active") is True and before.get("is_active") is False
                      else "CATALOG_DEACTIVATED" if changes.get("is_active") is False and before.get("is_active") is True
                      else "CATALOG_UPDATED",
                      {"code": item.code, "before": before, "after": changes})
    db.commit()
    return catalog_dict(db, item)


def revision_dict(item: CatalogRevision) -> dict:
    return {"id": item.id, "catalog_id": item.catalog_id, "revision_code": item.revision_code,
            "status": item.status, "change_note": item.change_note,
            "created_at": item.created_at, "updated_at": item.updated_at,
            "published_at": item.published_at}


def revisions(db: Session, catalog_id: int) -> list[dict]:
    catalog(db, catalog_id)
    return [revision_dict(item) for item in db.scalars(
        select(CatalogRevision).where(CatalogRevision.catalog_id == catalog_id)
        .order_by(CatalogRevision.created_at.desc(), CatalogRevision.id.desc())).all()]


def create_revision(db: Session, actor: User, catalog_id: int, data: RevisionCreate) -> dict:
    if "status" in data.model_fields_set:
        raise fail("catalog_revision_status_managed", 422)
    item = catalog(db, catalog_id, lock=True)
    if not item.is_active:
        raise fail("catalog_inactive")
    revision = CatalogRevision(catalog_id=item.id, revision_code=data.revision_code,
                               change_note=data.change_note, status="DRAFT", created_by_id=actor.id)
    db.add(revision)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise fail("catalog_revision_duplicate") from exc
    add_audit_log(db, actor, "catalog_revision", revision.id, "CATALOG_REVISION_CREATED",
                  {"catalog_code": item.code, "revision_code": revision.revision_code})
    db.commit()
    return revision_dict(revision)


def update_revision(db: Session, actor: User, revision_id: int, data: RevisionUpdate) -> dict:
    if "status" in data.model_fields_set:
        raise fail("catalog_revision_status_managed", 422)
    if "revision_code" in data.model_fields_set:
        raise fail("catalog_revision_code_immutable")
    revision = db.scalar(select(CatalogRevision).where(CatalogRevision.id == revision_id)
                         .with_for_update().execution_options(populate_existing=True))
    if revision is None:
        raise fail("catalog_revision_not_found", 404)
    if revision.status != "DRAFT":
        raise fail("catalog_revision_immutable")
    item = catalog(db, revision.catalog_id)
    if not item.is_active:
        raise fail("catalog_inactive")
    if "change_note" in data.model_fields_set:
        before = revision.change_note
        revision.change_note = data.change_note
        revision.updated_at = utcnow()
        add_audit_log(db, actor, "catalog_revision", revision.id, "CATALOG_REVISION_UPDATED",
                      {"catalog_code": item.code, "revision_code": revision.revision_code,
                       "before": {"change_note": before}, "after": {"change_note": revision.change_note}})
    db.commit()
    return revision_dict(revision)


def eligible_assets(db: Session, catalog_id: int, search: str | None = None) -> list[dict]:
    item = catalog(db, catalog_id)
    query = (select(Machine).outerjoin(CatalogAssetBinding,
                                      CatalogAssetBinding.machine_id == Machine.id)
             .where(Machine.category_id == item.asset_category_id, Machine.is_active.is_(True),
                    CatalogAssetBinding.id.is_(None)))
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(Machine.inventory_number.ilike(term), Machine.name.ilike(term),
                                Machine.brand.ilike(term), Machine.model.ilike(term)))
    return [repository.asset_dict(machine) for machine in db.scalars(
        query.order_by(Machine.inventory_number).limit(100)).all()]


def bind_asset(db: Session, actor: User, catalog_id: int, machine_id: int) -> dict:
    # PostgreSQL row lock serializes attempts to bind the same machine. The
    # unique machine_id constraint is the final race-safe guard on both engines.
    machine = db.scalar(select(Machine).where(Machine.id == machine_id)
                        .with_for_update().execution_options(populate_existing=True))
    if machine is None:
        raise fail("catalog_asset_not_found", 404)
    item = catalog(db, catalog_id, lock=True)
    if not item.is_active:
        raise fail("catalog_inactive")
    category_for_builder(db, item.asset_category_id)
    if not machine.is_active:
        raise fail("catalog_asset_inactive")
    if machine.category_id != item.asset_category_id:
        raise fail("catalog_asset_category_mismatch")
    existing = db.scalar(select(CatalogAssetBinding).where(CatalogAssetBinding.machine_id == machine_id))
    if existing:
        raise fail("catalog_asset_already_bound")
    binding = CatalogAssetBinding(catalog_id=item.id, machine_id=machine_id, created_by_id=actor.id)
    db.add(binding)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise fail("catalog_asset_already_bound") from exc
    add_audit_log(db, actor, "catalog_asset_binding", binding.id, "CATALOG_ASSET_BOUND",
                  {"catalog_code": item.code, "machine_id": machine_id})
    db.commit()
    return repository.asset_dict(machine)


def unbind_asset(db: Session, actor: User, catalog_id: int, machine_id: int) -> None:
    item = catalog(db, catalog_id, lock=True)
    binding = db.scalar(select(CatalogAssetBinding).where(
        CatalogAssetBinding.catalog_id == catalog_id, CatalogAssetBinding.machine_id == machine_id)
        .with_for_update())
    if binding is None:
        raise fail("catalog_asset_binding_not_found", 404)
    if db.scalar(select(CatalogRevision.id).where(
        CatalogRevision.catalog_id == catalog_id, CatalogRevision.status == "PUBLISHED").limit(1)):
        raise fail("catalog_asset_binding_protected")
    add_audit_log(db, actor, "catalog_asset_binding", binding.id, "CATALOG_ASSET_UNBOUND",
                  {"catalog_code": item.code, "machine_id": machine_id})
    db.delete(binding)
    db.commit()
