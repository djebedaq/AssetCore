"""Existing typed asset-field validation and updates with unchanged audit history."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..industrial_schemas import CustomFieldValuesUpdate
from ..models import CategoryFieldDefinition, FieldType, Machine, MachineFieldValue, User
from ..persistence import _commit
from ..workflow import add_machine_event, business_conflict


def _validated_custom_field_value(
    field: CategoryFieldDefinition, raw_value: str | None
) -> str | None:
    value = raw_value.strip() if raw_value is not None else None
    if value == "":
        value = None
    if value is None:
        if field.is_required:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "required_custom_field",
                    "message": f"Полето „{field.label_bg}“ е задължително.",
                    "field_id": field.id,
                },
            )
        return None
    normalized_value = value
    try:
        if field.field_type == FieldType.INTEGER.value:
            normalized_value = str(int(value))
        elif field.field_type == FieldType.DECIMAL.value:
            decimal_value = Decimal(value)
            if not decimal_value.is_finite():
                raise InvalidOperation
            normalized_value = format(decimal_value.normalize(), "f")
        elif field.field_type == FieldType.DATE.value:
            normalized_value = date.fromisoformat(value).isoformat()
        elif field.field_type == FieldType.BOOLEAN.value:
            normalized = value.lower()
            if normalized not in {"true", "false", "1", "0"}:
                raise ValueError
            normalized_value = "true" if normalized in {"true", "1"} else "false"
        elif field.field_type == FieldType.SELECT.value:
            options = field.options or []
            if value not in options:
                raise ValueError
        rules = field.validation_rules or {}
        if field.field_type in {FieldType.INTEGER.value, FieldType.DECIMAL.value}:
            numeric = Decimal(normalized_value)
            if rules.get("min") is not None and numeric < Decimal(str(rules["min"])):
                raise ValueError
            if rules.get("max") is not None and numeric > Decimal(str(rules["max"])):
                raise ValueError
        if rules.get("min_length") is not None and len(normalized_value) < int(rules["min_length"]):
            raise ValueError
        if rules.get("max_length") is not None and len(normalized_value) > int(rules["max_length"]):
            raise ValueError
        if rules.get("pattern") and re.fullmatch(str(rules["pattern"]), normalized_value) is None:
            raise ValueError
    except (InvalidOperation, ValueError, TypeError, re.error):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_custom_field_value",
                "message": f"Стойността за поле „{field.label_bg}“ е невалидна.",
                "field_id": field.id,
                "field_type": field.field_type,
            },
        ) from None
    return normalized_value


def update_custom_fields(
    machine_id: int, payload: CustomFieldValuesUpdate, user: User, db: Session
) -> dict:
    machine = db.get(Machine, machine_id)
    if machine is None:
        raise HTTPException(404, "Машината не е намерена.")
    field_ids = [item.field_id for item in payload.values]
    fields = (
        db.scalars(
            select(CategoryFieldDefinition).where(CategoryFieldDefinition.id.in_(field_ids))
        ).all()
        if field_ids
        else []
    )
    by_id = {field.id: field for field in fields}
    if len(by_id) != len(field_ids):
        raise HTTPException(404, "Едно или повече потребителски полета не са намерени.")
    current_values = {
        item.field_id: item
        for item in db.scalars(
            select(MachineFieldValue).where(MachineFieldValue.machine_id == machine.id)
        ).all()
    }
    previous = {
        by_id[field_id].code: current_values.get(field_id).value
        if field_id in current_values
        else None
        for field_id in field_ids
    }
    normalized: dict[int, str | None] = {}
    for item in payload.values:
        field = by_id[item.field_id]
        if machine.category_id != field.category_id:
            raise business_conflict(
                "field_category_mismatch",
                f"Полето „{field.label_bg}“ не принадлежи към категорията на машината.",
            )
        normalized[field.id] = _validated_custom_field_value(field, item.value)
        value = current_values.get(field.id)
        if value is None:
            value = MachineFieldValue(machine_id=machine.id, field_id=field.id)
            db.add(value)
            current_values[field.id] = value
        value.value = normalized[field.id]
        value.updated_by_id = user.id
    required_fields = db.scalars(
        select(CategoryFieldDefinition).where(
            CategoryFieldDefinition.category_id == machine.category_id,
            CategoryFieldDefinition.is_active.is_(True),
            CategoryFieldDefinition.is_required.is_(True),
        )
    ).all()
    for field in required_fields:
        candidate = normalized.get(
            field.id,
            current_values.get(field.id).value if field.id in current_values else None,
        )
        _validated_custom_field_value(field, candidate)
    changed = {
        by_id[field_id].code: normalized[field_id]
        for field_id in field_ids
        if previous[by_id[field_id].code] != normalized[field_id]
    }
    add_machine_event(
        db,
        machine,
        user,
        "CUSTOM_FIELDS_UPDATED",
        details={"field_ids": field_ids, "previous": previous, "new": changed},
    )
    add_audit_log(
        db,
        user,
        "machine",
        machine.id,
        "Обновени конфигурируеми полета",
        {"field_ids": field_ids, "previous": previous, "new": changed},
    )
    _commit(db)
    return {
        "message": "Потребителските полета са обновени.",
        "machine_id": machine.id,
        "values": [{"field_id": field_id, "value": normalized[field_id]} for field_id in field_ids],
    }
