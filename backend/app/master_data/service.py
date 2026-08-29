"""Existing reference-data operations; normalization, audit and commits are unchanged."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..audit import add_audit_log
from ..industrial_schemas import (
    CategoryCreate,
    CategoryFieldCreate,
    DepartmentCreate,
    DepartmentUpdate,
    LocationAdminCreate,
    LocationAdminUpdate,
)
from ..models import AssetCategory, CategoryFieldDefinition, Department, Location, User
from ..persistence import _commit
from ..workflow import business_conflict
from .serializers import _category_field_dict, _department_dict, _location_dict


def locations(_: User, db: Session) -> list[Location]:
    return db.scalars(select(Location).order_by(Location.name)).all()


def list_categories(_: User, db: Session) -> list[dict]:
    categories = db.scalars(
        select(AssetCategory)
        .options(selectinload(AssetCategory.fields))
        .where(AssetCategory.is_active.is_(True))
        .order_by(AssetCategory.name_bg)
    ).all()
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
            "is_active": category.is_active,
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
    category = AssetCategory(**payload.model_dump())
    db.add(category)
    db.flush()
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
    field = CategoryFieldDefinition(category_id=category_id, **payload.model_dump(mode="json"))
    db.add(field)
    db.flush()
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
