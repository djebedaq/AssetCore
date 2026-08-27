"""Existing machine CRUD and QR behavior, including original transaction boundaries."""

from __future__ import annotations

import io

import qrcode
from fastapi import HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..audit import add_audit_log
from ..models import AssetCategory, Machine, MachineStatus, Repair, RepairStatus, User, utcnow
from ..permissions import is_observer
from ..schemas import MachineCreate, MachineUpdate
from ..settings import settings
from ..workflow import add_machine_event, ensure_machine_transition
from .queries import _active_transfer
from .serializers import _limited_machine


def machines(user: User, db: Session) -> list[Machine] | list[dict]:
    items = db.scalars(
        select(Machine)
        .options(joinedload(Machine.location))
        .order_by(Machine.pressure_bar.desc(), Machine.inventory_number)
    ).all()
    return [_limited_machine(item) for item in items] if is_observer(user) else items


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
    category = db.get(AssetCategory, data.category_id) if data.category_id is not None else None
    if data.category_id is not None and category is None:
        raise HTTPException(404, "Категорията не е намерена")
    values = data.model_dump(mode="json")
    if category is not None:
        values["category"] = category.code
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
    category = (
        db.get(AssetCategory, changes["category_id"])
        if changes.get("category_id") is not None
        else None
    )
    if changes.get("category_id") is not None and category is None:
        raise HTTPException(404, "Категорията не е намерена")
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
    if category is not None:
        item.category = category.code
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


def qr(machine_id: int, request: Request, _: User, db: Session) -> Response:
    item = db.get(Machine, machine_id)
    if not item:
        raise HTTPException(404, "Машината не е намерена")
    base_url = (settings.public_base_url or str(request.base_url)).rstrip("/")
    image = qrcode.make(f"{base_url}/machine/{item.id}")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return Response(output.getvalue(), media_type="image/png")
