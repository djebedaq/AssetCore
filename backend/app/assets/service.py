"""Existing machine CRUD and QR behavior, including original transaction boundaries."""

from __future__ import annotations

import io

import qrcode
from fastapi import HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..audit import add_audit_log
from ..models import AssetCategory, Machine, MachineStatus, Repair, RepairStatus, User, utcnow
from ..permissions import is_observer
from ..schemas import MachineCreate, MachineUpdate
from ..settings import settings
from ..workflow import add_machine_event, ensure_machine_transition
from .native_fields import NativeFieldCapabilityError, validate_native_asset_fields
from .queries import _active_transfer
from .serializers import _limited_machine


def machines(user: User, db: Session, category_id: int | None = None) -> list[Machine] | list[dict]:
    if category_id is not None and db.get(AssetCategory, category_id) is None:
        raise HTTPException(404, detail={"code": "category_not_found", "message": "Категорията не е намерена."})
    statement = select(Machine).options(joinedload(Machine.location))
    if category_id is not None:
        statement = statement.where(Machine.category_id == category_id)
    items = db.scalars(statement.order_by(Machine.inventory_number)).all()
    return [_limited_machine(item) for item in items] if is_observer(user) else items


def category_navigation(user: User, db: Session) -> list[dict]:
    """One grouped count for the same unrestricted machine population as /machines.

    Inactive categories with assets remain visible; empty inactive categories do not.
    Names are sorted in Bulgarian with code and id tie-breakers for stable navigation.
    """
    rows = db.execute(
        select(AssetCategory, func.count(Machine.id))
        .outerjoin(Machine, Machine.category_id == AssetCategory.id)
        .group_by(AssetCategory.id)
    ).all()
    return [
        {
            "id": category.id,
            "code": category.code,
            "name_bg": category.name_bg,
            "name_en": category.name_en,
            "name_ru": category.name_ru,
            "is_active": category.is_active,
            "asset_count": count,
            "has_pressure": "HAS_PRESSURE" in (category.capabilities or []),
        }
        for category, count in sorted(
            rows, key=lambda row: (row[0].name_bg.casefold(), row[0].code, row[0].id)
        )
        if category.is_active or count > 0
    ]


def machine(machine_id: int, user: User, db: Session) -> Machine | dict:
    item = db.scalar(
        select(Machine).options(joinedload(Machine.location)).where(Machine.id == machine_id)
    )
    if not item:
        raise HTTPException(404, "Машината не е намерена")
    return _limited_machine(item) if is_observer(user) else item


def create_machine(data: MachineCreate, user: User, db: Session) -> Machine:
    if db.scalar(select(Machine).where(Machine.inventory_number == data.inventory_number)):
        raise HTTPException(409, "Дублиран инвентарен номер")
    category = _resolve_category(db, data.category_id, data.category)
    values = data.model_dump(mode="json")
    values["category_id"] = category.id
    values["category"] = category.code
    _require_native_fields(category, pressure_bar=values["pressure_bar"])
    item = Machine(**values)
    db.add(item)
    db.flush()
    add_machine_event(
        db,
        item,
        user,
        "MACHINE_CREATED",
        new_status=item.status,
        new_location_id=item.location_id,
        details={"inventory_number": item.inventory_number},
    )
    add_audit_log(db, user, "machine", item.id, "Създадена машина", values)
    db.commit()
    return db.scalar(
        select(Machine).options(joinedload(Machine.location)).where(Machine.id == item.id)
    )


def update_machine(machine_id: int, data: MachineUpdate, user: User, db: Session) -> Machine:
    item = db.get(Machine, machine_id)
    if not item:
        raise HTTPException(404, "Машината не е намерена")
    changes = data.model_dump(exclude_unset=True, mode="json")
    category = None
    if "category_id" in changes or "category" in changes:
        category = _resolve_category(
            db, changes.get("category_id"), changes.get("category"),
            current=item.category_definition,
        )
        changes["category_id"] = category.id
        changes["category"] = category.code
    resolved_category = category or item.category_definition
    if resolved_category is not None:
        _require_native_fields(
            resolved_category,
            pressure_bar=changes.get("pressure_bar", item.pressure_bar),
        )
    elif "pressure_bar" in changes:
        raise HTTPException(
            422, detail={"code": "category_required", "message": "Изберете съществуваща категория."},
        )
    active = _active_transfer(db, machine_id)
    if "status" in changes:
        requested_status = changes["status"]
        open_repair = db.scalar(
            select(Repair.id).where(
                Repair.machine_id == machine_id,
                Repair.status != RepairStatus.COMPLETED.value,
            )
        )
        authoritative_status = (
            MachineStatus.ISSUED.value
            if active
            else MachineStatus.REPAIR.value
            if open_repair is not None
            else MachineStatus.READY.value
        )
        if requested_status != authoritative_status:
            raise HTTPException(
                409,
                detail={
                    "code": "authoritative_machine_status_conflict",
                    "message": (
                        f"Статусът на машина №{item.inventory_number} не може да бъде "
                        f"сменен на „{requested_status}“. Текущите предавания и "
                        f"ремонтни карти изискват статус „{authoritative_status}“."
                    ),
                },
            )
        ensure_machine_transition(item.status, requested_status)
    before = {"status": item.status, "location_id": item.location_id}
    for key, value in changes.items():
        setattr(item, key, value)
    item.updated_at = utcnow()
    add_machine_event(
        db,
        item,
        user,
        "MACHINE_UPDATED",
        previous_status=before["status"],
        new_status=item.status,
        previous_location_id=before["location_id"],
        new_location_id=item.location_id,
        details={"changed_fields": sorted(changes)},
    )
    add_audit_log(
        db,
        user,
        "machine",
        item.id,
        "Актуализирана машина",
        {"преди": before, "след": changes},
    )
    db.commit()
    return db.scalar(
        select(Machine).options(joinedload(Machine.location)).where(Machine.id == item.id)
    )


def _resolve_category(
    db: Session, category_id: int | None, code: str | None,
    *, current: AssetCategory | None = None,
) -> AssetCategory:
    """Resolve legacy code writes and reject contradictory category identities."""
    if category_id is not None:
        category = db.get(AssetCategory, category_id)
        if category is None:
            raise HTTPException(404, "Категорията не е намерена")
    elif code:
        category = db.scalar(select(AssetCategory).where(AssetCategory.code == code))
    else:
        category = current
    if category is None:
        raise HTTPException(422, detail={"code": "category_required", "message": "Изберете съществуваща категория."})
    if code is not None and code != category.code:
        raise HTTPException(409, detail={"code": "category_mismatch", "message": "Категорията не съответства на category_id."})
    if not category.is_active and (current is None or current.id != category.id):
        raise HTTPException(422, detail={"code": "category_inactive", "message": "Категорията е неактивна."})
    return category


def _require_native_fields(category: AssetCategory, *, pressure_bar: int | None) -> None:
    try:
        validate_native_asset_fields(category, pressure_bar=pressure_bar)
    except NativeFieldCapabilityError as exc:
        raise HTTPException(
            422, detail={"code": exc.code, "message": str(exc)},
        ) from exc


def qr(machine_id: int, request: Request, _: User, db: Session) -> Response:
    item = db.get(Machine, machine_id)
    if not item:
        raise HTTPException(404, "Машината не е намерена")
    base_url = (settings.public_base_url or str(request.base_url)).rstrip("/")
    image = qrcode.make(f"{base_url}/machine/{item.id}")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return Response(output.getvalue(), media_type="image/png")
