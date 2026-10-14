"""Central binding reads and atomic writes. No nested commits or history deletion.

Lock order: machines (ascending), catalogs (ascending), categories (ascending),
bindings (ascending). Machine identity edits acquire catalogs before categories
too. Catalog edits/publication never acquire machine locks.
"""

import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..models import (
    AssetCategory,
    AuditLog,
    CatalogAssetBinding,
    CatalogDefinition,
    CatalogRevision,
    Machine,
    utcnow,
)
from .repository import asset_dict
from .schemas import BatchBind, BatchUnbind
from .service import compatibility, fail
from .visual_sources import lock_catalog


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _lock(db, machine_ids, catalog_ids):
    # SQLite's first write serializes authoritative reads, including absent pairs.
    if db.get_bind().dialect.name == "sqlite":
        db.execute(update(Machine).where(Machine.id.in_(machine_ids))
                   .values(updated_at=Machine.updated_at).execution_options(synchronize_session=False))
    list(db.scalars(select(Machine).where(Machine.id.in_(machine_ids)).order_by(Machine.id)
                    .with_for_update().execution_options(populate_existing=True)))
    for identity in sorted(set(catalog_ids)):
        if lock_catalog(db, identity) is None:
            raise fail("catalog_definition_not_found", 404)
    category_ids = select(CatalogDefinition.asset_category_id).where(CatalogDefinition.id.in_(catalog_ids))
    list(db.scalars(select(AssetCategory).where(AssetCategory.id.in_(category_ids))
                    .order_by(AssetCategory.id).with_for_update(read=True)
                    .execution_options(populate_existing=True)))


def _context(db, catalog_id, machine_ids):
    item = db.scalar(select(CatalogDefinition).where(CatalogDefinition.id == catalog_id)
                     .execution_options(populate_existing=True))
    if item is None:
        raise fail("catalog_definition_not_found", 404)
    category = db.scalar(select(AssetCategory).where(AssetCategory.id == item.asset_category_id)
                         .execution_options(populate_existing=True))
    revision = db.scalar(select(CatalogRevision).where(CatalogRevision.catalog_id == catalog_id,
                                                      CatalogRevision.status == "PUBLISHED"))
    machines = {m.id: m for m in db.scalars(select(Machine).where(Machine.id.in_(machine_ids))
                                           .execution_options(populate_existing=True))}
    pairs = {b.machine_id: b for b in db.scalars(select(CatalogAssetBinding).where(
        CatalogAssetBinding.catalog_id == catalog_id, CatalogAssetBinding.machine_id.in_(machine_ids))
        .execution_options(populate_existing=True))}
    return item, category, revision, machines, pairs


def preview(db: Session, data: BatchBind):
    item, category, revision, machines, pairs = _context(db, data.catalog_id, data.machine_ids)
    rows = []
    for identity in data.machine_ids:
        machine, pair = machines.get(identity), pairs.get(identity)
        match = compatibility(item, machine) if machine else None
        code = (
            "catalog_asset_not_found" if machine is None else
            "catalog_inactive" if not item.is_active else
            "catalog_category_inactive" if category is None or not category.is_active else
            "catalog_category_not_supported" if "HAS_PARTS_CATALOG" not in (category.capabilities or []) else
            "catalog_asset_inactive" if not machine.is_active else
            "catalog_asset_category_mismatch" if machine.category_id != category.id else
            "catalog_not_published" if revision is None else
            "catalog_asset_already_bound" if pair and pair.is_active else
            "catalog_asset_model_mismatch" if match == "INCOMPATIBLE" else
            "catalog_asset_compatibility_confirmation_required" if match == "AMBIGUOUS" and identity not in data.confirmed_machine_ids else
            None
        )
        rows.append({**(asset_dict(machine) if machine else {"id": identity}),
                     "compatibility": match, "code": code,
                     "compatibility_confirmed": identity in data.confirmed_machine_ids})
    state = {"catalog": [item.id, item.is_active, item.asset_category_id, item.manufacturer,
                         item.model_reference, item.updated_at],
             "category": [category.is_active, category.capabilities] if category else None,
             "revision": revision.id if revision else None,
             "machines": [[identity, machines[identity].updated_at if identity in machines else None,
                           pairs[identity].is_active if identity in pairs else None] for identity in data.machine_ids],
             "rows": rows}
    return {"catalog_id": item.id, "published_revision": {"id": revision.id, "revision_code": revision.revision_code} if revision else None,
            "machines": rows, "ready": all(row["code"] is None for row in rows), "digest": digest(state)}


def bind(db: Session, actor, data: BatchBind, *, require_preview=True):
    try:
        _lock(db, data.machine_ids, [data.catalog_id])
        plan = preview(db, data)
        if not plan["ready"]:
            issues = [row for row in plan["machines"] if row["code"]]
            raise HTTPException(409, detail={"code": issues[0]["code"], "issues": issues})
        if require_preview and (not data.expected_digest or data.expected_digest != plan["digest"]):
            raise fail("catalog_bindings_stale")
        item, _, _, machines, pairs = _context(db, data.catalog_id, data.machine_ids)
        operation_id = str(uuid4())
        result = []
        for row in plan["machines"]:
            identity = row["id"]
            binding = pairs.get(identity) or CatalogAssetBinding(
                catalog_id=item.id, machine_id=identity, created_by_id=actor.id)
            binding.is_active, binding.deactivated_at = True, None
            db.add(binding)
            db.flush()
            add_audit_log(db, actor, "catalog_asset_binding", binding.id, "CATALOG_ASSET_BOUND",
                          {"operation_id": operation_id, "catalog_id": item.id, "catalog_code": item.code,
                           "machine_id": identity, "machine_ids": data.machine_ids,
                           "published_revision_id": plan["published_revision"]["id"],
                           "compatibility": row["compatibility"],
                           "compatibility_confirmed": row["compatibility_confirmed"]}, operation_reference=operation_id)
            result.append({"binding_id": binding.id, **asset_dict(machines[identity])})
        db.commit()
        return {"operation_id": operation_id, "catalog_id": data.catalog_id,
                "published_revision": plan["published_revision"], "count": len(result), "machines": result}
    except IntegrityError as exc:
        db.rollback()
        raise fail("catalog_asset_already_bound") from exc
    except Exception:
        db.rollback()
        raise


def _search(term):
    # Literal substring search, including serial number; wildcards are escaped.
    value = (term or "").strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return or_(*(field.ilike(f"%{value}%", escape="\\") for field in
                 [Machine.inventory_number, Machine.name, Machine.brand, Machine.model, Machine.serial_number]))


def machine_page(db, category_id, catalog_id=None, search=None, offset=0, limit=50):
    condition = [Machine.category_id == category_id, _search(search)]
    total = db.scalar(select(func.count(Machine.id)).where(*condition))
    machines = db.scalars(select(Machine).where(*condition).order_by(Machine.inventory_number, Machine.id)
                          .offset(offset).limit(limit)).all()
    bound = set(db.scalars(select(CatalogAssetBinding.machine_id).where(
        CatalogAssetBinding.catalog_id == catalog_id, CatalogAssetBinding.is_active.is_(True),
        CatalogAssetBinding.machine_id.in_([m.id for m in machines])))) if catalog_id else set()
    item = db.get(CatalogDefinition, catalog_id) if catalog_id else None
    return {"total": total, "offset": offset, "limit": limit, "items": [
        {**asset_dict(m), "bound": m.id in bound, "compatibility": compatibility(item, m) if item else None}
        for m in machines]}


def binding_page(db, category_id=None, catalog_id=None, machine_id=None, search=None, offset=0, limit=50,
                 *, identities=None):
    # One grouped audit query supplies an optimistic generation even after an
    # unbind/rebind cycle (ABA). Creation timestamps and historical IDs stay intact.
    audits = select(AuditLog.entity_id, func.max(AuditLog.id).label("version")).where(
        AuditLog.entity_type == "catalog_asset_binding").group_by(AuditLog.entity_id).subquery()
    query = select(CatalogAssetBinding, Machine, CatalogDefinition, CatalogRevision, func.coalesce(audits.c.version, 0)).join(
        Machine, Machine.id == CatalogAssetBinding.machine_id).join(
        CatalogDefinition, CatalogDefinition.id == CatalogAssetBinding.catalog_id).outerjoin(
        CatalogRevision, (CatalogRevision.catalog_id == CatalogDefinition.id) & (CatalogRevision.status == "PUBLISHED")).outerjoin(
        audits, audits.c.entity_id == CatalogAssetBinding.id).where(CatalogAssetBinding.is_active.is_(True))
    if identities is not None:
        query = query.where(CatalogAssetBinding.id.in_(identities))
    if category_id:
        query = query.where(CatalogDefinition.asset_category_id == category_id)
    if catalog_id:
        query = query.where(CatalogAssetBinding.catalog_id == catalog_id)
    if machine_id:
        query = query.where(CatalogAssetBinding.machine_id == machine_id)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(_search(search), CatalogDefinition.code.ilike(term),
                               CatalogDefinition.name_bg.ilike(term), CatalogDefinition.name_en.ilike(term), CatalogDefinition.name_ru.ilike(term)))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(CatalogAssetBinding.id).offset(offset).limit(limit)).all()
    result = []
    for binding, machine, item, revision, version in rows:
        state = [binding.id, binding.catalog_id, binding.machine_id, binding.is_active,
                 binding.deactivated_at, version, item.updated_at, machine.updated_at, revision.id if revision else None]
        result.append({"id": binding.id, "catalog_id": item.id, "machine_id": machine.id,
                       "category_id": item.asset_category_id, "machine": asset_dict(machine),
                       "catalog": {"code": item.code, "name_bg": item.name_bg, "name_en": item.name_en, "name_ru": item.name_ru},
                       "status": "ACTIVE" if revision else "PENDING_PUBLICATION",
                       "published_revision": {"id": revision.id, "revision_code": revision.revision_code} if revision else None,
                       "expected_digest": digest(state)})
    return {"total": total, "offset": offset, "limit": limit, "items": result}


def unbind(db: Session, actor, data: BatchUnbind, *, require_preview=True):
    try:
        _lock(db, [r.machine_id for r in data.bindings], [r.catalog_id for r in data.bindings])
        identities = [r.binding_id for r in data.bindings]
        list(db.scalars(select(CatalogAssetBinding).where(CatalogAssetBinding.id.in_(identities))
                        .order_by(CatalogAssetBinding.id).with_for_update().execution_options(populate_existing=True)))
        current = {r["id"]: r for r in binding_page(db, identities=identities, limit=500)["items"]}
        for requested in data.bindings:
            row = current.get(requested.binding_id)
            if row is None or row["machine_id"] != requested.machine_id or row["catalog_id"] != requested.catalog_id:
                raise HTTPException(409, detail={"code": "catalog_asset_binding_not_found", "binding_id": requested.binding_id})
            if require_preview and row["expected_digest"] != requested.expected_digest:
                raise HTTPException(409, detail={"code": "catalog_bindings_stale", "binding_id": requested.binding_id})
        operation_id = str(uuid4())
        for requested in data.bindings:
            binding = db.get(CatalogAssetBinding, requested.binding_id)
            binding.is_active, binding.deactivated_at = False, utcnow()
            add_audit_log(db, actor, "catalog_asset_binding", binding.id, "CATALOG_ASSET_UNBOUND",
                          {"operation_id": operation_id, "catalog_id": binding.catalog_id,
                           "catalog_code": current[binding.id]["catalog"]["code"],
                           "machine_id": binding.machine_id, "binding_ids": identities}, operation_reference=operation_id)
        db.commit()
        return {"operation_id": operation_id, "count": len(identities), "binding_ids": identities}
    except Exception:
        db.rollback()
        raise
