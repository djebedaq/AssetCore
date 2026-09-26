"""Category and reference-data administration with audited, atomic changes."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..assets.custom_fields import _validated_custom_field_value
from ..audit import add_audit_log
from ..industrial_schemas import (
    CategoryCreate,
    CategoryFieldCreate,
    CategoryFieldUpdate,
    CategoryUpdate,
    DepartmentCreate,
    DepartmentUpdate,
    LocationAdminCreate,
    LocationAdminUpdate,
)
from ..models import (
    AssetCategory,
    CategoryFieldDefinition,
    Department,
    Location,
    Machine,
    MachineFieldValue,
    User,
)
from ..persistence import _commit
from ..workflow import business_conflict
from .capabilities import CAPABILITIES
from .serializers import _category_field_dict, _department_dict, _location_dict


def locations(_: User, db: Session) -> list[Location]:
    return db.scalars(select(Location).order_by(Location.name)).all()


def list_categories(_: User, db: Session) -> list[dict]:
    categories = db.scalars(
        select(AssetCategory)
        .options(selectinload(AssetCategory.fields))
        .order_by(AssetCategory.name_bg)
    ).all()
    counts = dict(db.execute(
        select(Machine.category_id, func.count(Machine.id)).group_by(Machine.category_id)
    ).all())
    return [
        {
            "id": category.id,
            "code": category.code,
            "name_bg": category.name_bg,
            "name_en": category.name_en,
            "name_ru": category.name_ru,
            "description": category.description,
            "icon": category.icon,
            "validation_rules": category.validation_rules,
            "document_types": category.document_types,
            "checklists": category.checklists,
            "status_codes": category.status_codes,
            "capabilities": category.capabilities,
            "is_active": category.is_active,
            "asset_count": counts.get(category.id, 0),
            "created_at": category.created_at,
            "fields": [
                _category_field_dict(item)
                for item in sorted(
                    category.fields, key=lambda item: (item.sort_order, item.id)
                )
            ],
        }
        for category in categories
    ]


def create_category(payload: CategoryCreate, user: User, db: Session) -> AssetCategory:
    if db.scalar(select(AssetCategory.id).where(AssetCategory.code == payload.code)) is not None:
        raise business_conflict("category_code_duplicate", "Вече съществува категория с този код.", category_code=payload.code)
    category = AssetCategory(**payload.model_dump())
    db.add(category)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise business_conflict("category_code_duplicate", "Вече съществува категория с този код.", category_code=payload.code) from exc
    add_audit_log(
        db, user, "asset_category", category.id, "Създадена категория", payload.model_dump()
    )
    _commit(db)
    db.refresh(category)
    return category


def create_category_field(
    category_id: int, payload: CategoryFieldCreate, user: User, db: Session
) -> CategoryFieldDefinition:
    if db.get(AssetCategory, category_id) is None:
        raise HTTPException(404, "Категорията не е намерена.")
    if db.scalar(select(CategoryFieldDefinition.id).where(
        CategoryFieldDefinition.category_id == category_id,
        CategoryFieldDefinition.code == payload.code,
    )) is not None:
        raise business_conflict("category_field_code_duplicate", "Вече съществува поле с този код в категорията.", field_code=payload.code)
    field = CategoryFieldDefinition(category_id=category_id, **payload.model_dump(mode="json"))
    db.add(field)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise business_conflict("category_field_code_duplicate", "Вече съществува поле с този код в категорията.", field_code=payload.code) from exc
    add_audit_log(
        db,
        user,
        "category_field",
        field.id,
        "Създадено конфигурируемо поле",
        payload.model_dump(mode="json"),
    )
    _commit(db)
    db.refresh(field)
    return field


def asset_capabilities() -> list[dict]:
    return [dict(item) for item in CAPABILITIES]


def _category_dict(category: AssetCategory) -> dict:
    return {
        "id": category.id, "code": category.code,
        "name_bg": category.name_bg, "name_en": category.name_en, "name_ru": category.name_ru,
        "description": category.description, "icon": category.icon,
        "validation_rules": category.validation_rules, "document_types": category.document_types,
        "checklists": category.checklists, "status_codes": category.status_codes,
        "capabilities": category.capabilities, "is_active": category.is_active,
        "created_at": category.created_at,
    }


def update_category(category_id: int, payload: CategoryUpdate, user: User, db: Session) -> dict:
    category = db.scalar(select(AssetCategory).where(AssetCategory.id == category_id).with_for_update().execution_options(populate_existing=True))
    if category is None:
        raise HTTPException(404, detail={"code": "category_not_found"})
    changes = payload.model_dump(exclude_unset=True)
    if "capabilities" in changes and "HAS_PRESSURE" in (category.capabilities or []) and "HAS_PRESSURE" not in (changes["capabilities"] or []):
        affected = db.scalar(select(func.count(Machine.id)).where(
            Machine.category_id == category_id, Machine.pressure_bar.is_not(None),
        )) or 0
        if affected:
            raise business_conflict(
                "category_capability_in_use", "Първо премахнете налягането от засегнатите активи.",
                capability="HAS_PRESSURE", affected_asset_count=affected,
            )
    previous = _category_dict(category)
    for key, value in changes.items():
        setattr(category, key, value)
    add_audit_log(db, user, "asset_category", category.id, "Обновена категория", {
        "previous": previous, "changes": changes,
    })
    _commit(db)
    db.refresh(category)
    return _category_dict(category)


def update_category_field(
    category_id: int, field_id: int, payload: CategoryFieldUpdate, user: User, db: Session,
) -> dict:
    field = db.scalar(select(CategoryFieldDefinition).where(
        CategoryFieldDefinition.id == field_id,
        CategoryFieldDefinition.category_id == category_id,
    ).with_for_update().execution_options(populate_existing=True))
    if field is None:
        raise HTTPException(404, detail={"code": "category_field_not_found"})
    changes = payload.model_dump(exclude_unset=True, mode="json")
    previous = _category_field_dict(field)
    candidate = {key: previous[key] for key in CategoryFieldCreate.model_fields}
    candidate.update({key: value for key, value in changes.items() if key in candidate})
    if any(key in changes for key in ("field_type", "options", "validation_rules")) or changes.get("is_active") is True:
        try:
            CategoryFieldCreate.model_validate(candidate)
        except ValidationError as exc:
            raise HTTPException(422, detail={"code": "invalid_category_field_definition", "message": "Невалидна конфигурация на полето."}) from exc
    # Reuse the same runtime validator without mutating stored values or the field.
    if any(key in changes for key in ("field_type", "options", "validation_rules")) or changes.get("is_active") is True:
        validation_field = SimpleNamespace(**{**previous, **changes})
        values = db.scalars(select(MachineFieldValue.value).where(
            MachineFieldValue.field_id == field.id, MachineFieldValue.value.is_not(None),
        )).all()
        for value in values:
            try:
                _validated_custom_field_value(validation_field, value)
            except HTTPException as exc:
                raise business_conflict(
                    "category_field_values_incompatible",
                    "Съществуващи стойности не съответстват на новата дефиниция.",
                    field_id=field.id,
                ) from exc
    for key, value in changes.items():
        setattr(field, key, value)
    add_audit_log(db, user, "category_field", field.id, "Обновено конфигурируемо поле", {
        "previous": previous, "changes": changes,
    })
    _commit(db)
    db.refresh(field)
    return _category_field_dict(field)


def list_departments(_: User, db: Session) -> list[dict]:
    items = db.scalars(select(Department).order_by(Department.code)).all()
    return [_department_dict(item) for item in items]


def admin_reference_data(_: User, db: Session) -> dict:
    locations = db.scalars(select(Location).order_by(Location.name)).all()
    departments = db.scalars(select(Department).order_by(Department.code)).all()
    return {
        "locations": [_location_dict(item) for item in locations],
        "departments": [_department_dict(item) for item in departments],
    }


def create_location(payload: LocationAdminCreate, user: User, db: Session) -> dict:
    name = payload.name.strip()
    if any(
        existing.casefold() == name.casefold()
        for existing in db.scalars(select(Location.name)).all()
    ):
        raise business_conflict(
            "location_duplicate",
            "Вече съществува местоположение със същото име.",
            name=name,
        )
    item = Location(name=name, description=payload.description)
    db.add(item)
    db.flush()
    add_audit_log(
        db,
        user,
        "location",
        item.id,
        "Добавено местоположение",
        {"name": item.name, "is_active": item.is_active},
    )
    _commit(db)
    db.refresh(item)
    return _location_dict(item)


def update_location(
    location_id: int, payload: LocationAdminUpdate, user: User, db: Session
) -> dict:
    item = db.get(Location, location_id)
    if item is None:
        raise HTTPException(404, "Местоположението не е намерено.")
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes:
        name = changes["name"].strip()
        duplicate = any(
            existing.casefold() == name.casefold()
            for existing in db.scalars(select(Location.name).where(Location.id != item.id)).all()
        )
        if duplicate:
            raise business_conflict(
                "location_duplicate",
                "Вече съществува местоположение със същото име.",
                name=name,
            )
        changes["name"] = name
    previous = _location_dict(item)
    for key, value in changes.items():
        setattr(item, key, value)
    add_audit_log(
        db,
        user,
        "location",
        item.id,
        "Обновено местоположение",
        {"previous": previous, "changes": changes},
    )
    _commit(db)
    db.refresh(item)
    return _location_dict(item)


def create_department(payload: DepartmentCreate, user: User, db: Session) -> dict:
    code = payload.code.strip().upper()
    if db.scalar(select(Department.id).where(Department.code == code)):
        raise business_conflict(
            "department_duplicate",
            "Вече съществува отдел със същия системен код.",
            department_code=code,
        )
    item = Department(**payload.model_dump(exclude={"code"}), code=code)
    db.add(item)
    db.flush()
    add_audit_log(
        db,
        user,
        "department",
        item.id,
        "Добавен отдел",
        {"code": item.code, "name_bg": item.name_bg, "is_active": item.is_active},
    )
    _commit(db)
    db.refresh(item)
    return _department_dict(item)


def update_department(
    department_id: int, payload: DepartmentUpdate, user: User, db: Session
) -> dict:
    item = db.get(Department, department_id)
    if item is None:
        raise HTTPException(404, "Отделът не е намерен.")
    changes = payload.model_dump(exclude_unset=True)
    if "code" in changes:
        code = changes["code"].strip().upper()
        duplicate = db.scalar(
            select(Department.id).where(Department.code == code, Department.id != item.id)
        )
        if duplicate:
            raise business_conflict(
                "department_duplicate",
                "Вече съществува отдел със същия системен код.",
                department_code=code,
            )
        changes["code"] = code
    previous = _department_dict(item)
    for key, value in changes.items():
        setattr(item, key, value)
    add_audit_log(
        db,
        user,
        "department",
        item.id,
        "Обновен отдел",
        {"previous": previous, "changes": changes},
    )
    _commit(db)
    db.refresh(item)
    return _department_dict(item)
