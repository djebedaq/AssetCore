"""Draft repair-kit definitions bound to exact Builder parts and source pages."""

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..models import (
    CatalogRevisionArtifact,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
    CatalogRevisionRepairKit,
    CatalogRevisionRepairKitComponent,
    CatalogRevisionVisualPage,
    User,
    utcnow,
)
from .schemas import (
    RepairKitComponentCreate,
    RepairKitComponentUpdate,
    RepairKitCreate,
    RepairKitUpdate,
)
from .service import fail
from .visual_sources import _assembly, _meta


def _kit(db: Session, kit_id: int, *, mutate: bool = False):
    kit = db.get(CatalogRevisionRepairKit, kit_id)
    if kit is None:
        raise fail("catalog_repair_kit_not_found", 404)
    assembly, revision, catalog = _assembly(db, kit.assembly_id, mutate=mutate)
    if mutate:
        kit = db.scalar(select(CatalogRevisionRepairKit).where(CatalogRevisionRepairKit.id == kit_id)
                        .with_for_update().execution_options(populate_existing=True))
    if kit is None or kit.assembly_id != assembly.id:
        raise fail("catalog_repair_kit_not_found", 404)
    return kit, assembly, revision, catalog


def _component(db: Session, component_id: int, *, mutate: bool = False):
    component = db.get(CatalogRevisionRepairKitComponent, component_id)
    if component is None:
        raise fail("catalog_repair_kit_component_invalid", 404)
    kit, assembly, revision, catalog = _kit(db, component.kit_id, mutate=mutate)
    if mutate:
        component = db.scalar(select(CatalogRevisionRepairKitComponent)
                              .where(CatalogRevisionRepairKitComponent.id == component_id)
                              .with_for_update().execution_options(populate_existing=True))
    if component is None or component.kit_id != kit.id:
        raise fail("catalog_repair_kit_component_invalid", 404)
    return component, kit, assembly, revision, catalog


def _version(current: int, expected: int) -> None:
    if current != expected:
        raise fail("catalog_repair_kit_stale")


def _clean(values: dict) -> dict:
    cleaned = {}
    for key, value in values.items():
        if isinstance(value, str):
            value = value.strip()
            if any((ord(char) < 32 and char not in "\n\t") or 127 <= ord(char) <= 159 for char in value):
                raise fail("catalog_repair_kit_invalid", 422)
            value = value or None
        cleaned[key] = value
    return cleaned


def _names(values: dict) -> None:
    if not any(values.get(key) for key in ("name_bg", "name_en", "name_ru", "description")):
        raise fail("catalog_repair_kit_invalid", 422)


def _source_page(db: Session, assembly_id: int, page_id: int | None) -> None:
    if page_id is None:
        return
    allowed = db.scalar(select(CatalogRevisionVisualPage.id)
                        .join(CatalogRevisionArtifact,
                              CatalogRevisionVisualPage.artifact_id == CatalogRevisionArtifact.id)
                        .where(CatalogRevisionVisualPage.id == page_id,
                               CatalogRevisionVisualPage.role == "SPARE_PARTS_LIST",
                               CatalogRevisionArtifact.assembly_id == assembly_id))
    if allowed is None:
        raise fail("catalog_repair_kit_source_page_invalid", 422)


def _component_dict(db: Session, item: CatalogRevisionRepairKitComponent) -> dict:
    part = db.get(CatalogRevisionPart, item.part_id)
    mapped = part is not None and db.scalar(select(CatalogRevisionPartPageMap.id).where(
        CatalogRevisionPartPageMap.part_id == item.part_id).limit(1)) is not None
    fields = ("id", "assembly_id", "position", "part_number", "name_bg", "name_en", "name_ru", "description")
    part_fields = {key: getattr(part, key) if part is not None else None for key in fields}
    part_fields["validation_status"] = "READY" if mapped and any(
        (part.name_bg, part.name_en, part.name_ru, part.description)) else "INCOMPLETE"
    return {key: getattr(item, key) for key in (
        "id", "kit_id", "part_id", "quantity", "quantity_raw", "is_optional", "note",
        "sort_order", "version", "created_at", "updated_at")} | {"part": part_fields}


def _dict(db: Session, item: CatalogRevisionRepairKit) -> dict:
    components = [_component_dict(db, row) for row in db.scalars(
        select(CatalogRevisionRepairKitComponent)
        .where(CatalogRevisionRepairKitComponent.kit_id == item.id)
        .order_by(CatalogRevisionRepairKitComponent.sort_order, CatalogRevisionRepairKitComponent.id)).all()]
    incomplete = [row["part_id"] for row in components if row["part"]["validation_status"] != "READY"]
    valid_references = all(row["part"]["assembly_id"] == item.assembly_id for row in components)
    return {key: getattr(item, key) for key in (
        "id", "assembly_id", "code", "name_bg", "name_en", "name_ru", "description",
        "source_visual_page_id", "sort_order", "code_locked", "version", "created_at", "updated_at")} | {
            "components": components, "component_count": len(components),
            "validation_status": "READY" if components and valid_references and any((
                item.name_bg, item.name_en, item.name_ru, item.description)) else "INCOMPLETE",
            "incomplete_part_ids": incomplete,
        }


def list_kits(db: Session, assembly_id: int) -> list[dict]:
    _assembly(db, assembly_id)
    return [_dict(db, item) for item in db.scalars(select(CatalogRevisionRepairKit)
            .where(CatalogRevisionRepairKit.assembly_id == assembly_id)
            .order_by(CatalogRevisionRepairKit.sort_order, CatalogRevisionRepairKit.id)).all()]


def get_kit(db: Session, kit_id: int) -> dict:
    return _dict(db, _kit(db, kit_id)[0])


def create_kit(db: Session, actor: User, assembly_id: int, data: RepairKitCreate) -> dict:
    assembly, revision, catalog = _assembly(db, assembly_id, mutate=True)
    values = _clean(data.model_dump())
    _names(values)
    _source_page(db, assembly.id, values["source_visual_page_id"])
    item = CatalogRevisionRepairKit(assembly_id=assembly.id, created_by_id=actor.id, **values)
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise fail("catalog_repair_kit_duplicate") from exc
    add_audit_log(db, actor, "catalog_revision_repair_kit", item.id, "BUILDER_REPAIR_KIT_CREATED",
                  _meta(catalog, revision, assembly, kit_code=item.code,
                        source_visual_page_id=item.source_visual_page_id))
    db.commit()
    return _dict(db, item)


def update_kit(db: Session, actor: User, kit_id: int, data: RepairKitUpdate) -> dict:
    item, assembly, revision, catalog = _kit(db, kit_id, mutate=True)
    _version(item.version, data.expected_version)
    changes = _clean(data.model_dump(exclude_unset=True, exclude={"expected_version"}))
    values = {key: getattr(item, key) for key in ("name_bg", "name_en", "name_ru", "description")}
    values.update(changes)
    _names(values)
    if changes.get("code") is None and "code" in changes or changes.get("sort_order") is None and "sort_order" in changes:
        raise fail("catalog_repair_kit_invalid", 422)
    if "code" in changes and changes["code"] != item.code:
        if item.code_locked:
            raise fail("catalog_repair_kit_code_immutable")
    _source_page(db, assembly.id, values.get("source_visual_page_id", item.source_visual_page_id))
    before = {key: getattr(item, key) for key in changes}
    if any(before[key] != value for key, value in changes.items()):
        for key, value in changes.items():
            setattr(item, key, value)
        item.version += 1
        item.updated_at = utcnow()
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise fail("catalog_repair_kit_duplicate") from exc
        add_audit_log(db, actor, "catalog_revision_repair_kit", item.id, "BUILDER_REPAIR_KIT_UPDATED",
                      _meta(catalog, revision, assembly, kit_code=item.code, before=before, after=changes))
        db.commit()
    return _dict(db, item)


def delete_kit(db: Session, actor: User, kit_id: int, expected_version: int) -> None:
    item, assembly, revision, catalog = _kit(db, kit_id, mutate=True)
    _version(item.version, expected_version)
    component_ids = db.scalars(select(CatalogRevisionRepairKitComponent.id).where(
        CatalogRevisionRepairKitComponent.kit_id == item.id)).all()
    add_audit_log(db, actor, "catalog_revision_repair_kit", item.id, "BUILDER_REPAIR_KIT_DELETED",
                  _meta(catalog, revision, assembly, kit_code=item.code,
                        source_visual_page_id=item.source_visual_page_id, component_ids=component_ids))
    db.execute(delete(CatalogRevisionRepairKitComponent).where(CatalogRevisionRepairKitComponent.kit_id == item.id))
    db.delete(item)
    db.commit()


def add_component(db: Session, actor: User, kit_id: int, data: RepairKitComponentCreate) -> dict:
    kit, assembly, revision, catalog = _kit(db, kit_id, mutate=True)
    part = db.get(CatalogRevisionPart, data.part_id)
    if part is None:
        raise fail("catalog_repair_kit_component_invalid", 422)
    if part.assembly_id != assembly.id:
        raise fail("catalog_repair_kit_cross_assembly", 422)
    item = CatalogRevisionRepairKitComponent(kit_id=kit.id, part_id=part.id,
                                             created_by_id=actor.id, **_clean(data.model_dump(exclude={"part_id"})))
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise fail("catalog_repair_kit_component_duplicate") from exc
    kit.version += 1
    kit.code_locked = True
    kit.updated_at = utcnow()
    add_audit_log(db, actor, "catalog_revision_repair_kit_component", item.id,
                  "BUILDER_REPAIR_KIT_COMPONENT_ADDED",
                  _meta(catalog, revision, assembly, kit_code=kit.code, part_id=part.id,
                        position=part.position, quantity=str(item.quantity), is_optional=item.is_optional))
    db.commit()
    return _component_dict(db, item)


def update_component(db: Session, actor: User, component_id: int, data: RepairKitComponentUpdate) -> dict:
    item, kit, assembly, revision, catalog = _component(db, component_id, mutate=True)
    _version(item.version, data.expected_version)
    changes = _clean(data.model_dump(exclude_unset=True, exclude={"expected_version"}))
    if any(changes.get(key) is None for key in ("quantity", "is_optional", "sort_order") if key in changes):
        raise fail("catalog_repair_kit_component_invalid", 422)
    before = {key: getattr(item, key) for key in changes}
    if any(before[key] != value for key, value in changes.items()):
        for key, value in changes.items():
            setattr(item, key, value)
        item.version += 1
        item.updated_at = utcnow()
        kit.version += 1
        kit.updated_at = utcnow()
        add_audit_log(db, actor, "catalog_revision_repair_kit_component", item.id,
                      "BUILDER_REPAIR_KIT_COMPONENT_UPDATED",
                      _meta(catalog, revision, assembly, kit_code=kit.code,
                            part_id=item.part_id, before=before, after=changes))
        db.commit()
    return _component_dict(db, item)


def remove_component(db: Session, actor: User, component_id: int, expected_version: int) -> None:
    item, kit, assembly, revision, catalog = _component(db, component_id, mutate=True)
    _version(item.version, expected_version)
    add_audit_log(db, actor, "catalog_revision_repair_kit_component", item.id,
                  "BUILDER_REPAIR_KIT_COMPONENT_REMOVED",
                  _meta(catalog, revision, assembly, kit_code=kit.code, part_id=item.part_id))
    db.delete(item)
    kit.version += 1
    kit.updated_at = utcnow()
    db.commit()


def source_page_reference_count(db: Session, page_ids) -> int:
    return db.scalar(select(func.count(CatalogRevisionRepairKit.id)).where(
        CatalogRevisionRepairKit.source_visual_page_id.in_(page_ids))) or 0


def remove_assembly_kits(db: Session, assembly_id: int) -> dict:
    kit_ids = select(CatalogRevisionRepairKit.id).where(CatalogRevisionRepairKit.assembly_id == assembly_id)
    kit_count = db.scalar(select(func.count(CatalogRevisionRepairKit.id)).where(
        CatalogRevisionRepairKit.assembly_id == assembly_id)) or 0
    component_count = db.scalar(select(func.count(CatalogRevisionRepairKitComponent.id)).where(
        CatalogRevisionRepairKitComponent.kit_id.in_(kit_ids))) or 0
    db.execute(delete(CatalogRevisionRepairKitComponent).where(
        CatalogRevisionRepairKitComponent.kit_id.in_(kit_ids)))
    db.execute(delete(CatalogRevisionRepairKit).where(CatalogRevisionRepairKit.assembly_id == assembly_id))
    return {"repair_kit_count": kit_count, "repair_kit_component_count": component_count}
