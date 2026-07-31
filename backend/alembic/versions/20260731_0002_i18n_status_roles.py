"""Add language preferences and migrate translated statuses to stable codes.

Revision ID: 20260731_0002
Revises: 20260731_0001
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260731_0002"
down_revision = "20260731_0001"
branch_labels = None
depends_on = None


MACHINE_STATUSES = {
    "Готова": "READY",
    "Издадена": "ISSUED",
    "В употреба": "IN_USE",
    "Върната": "RETURNED",
    "За преглед": "INSPECTION",
    "Преглед": "INSPECTION",
    "Почистване": "CLEANING",
    "В ремонт": "REPAIR",
    "Ремонт": "REPAIR",
    "Чака одобрение": "WAITING_APPROVAL",
    "Изчаква одобрение": "WAITING_APPROVAL",
    "Чака части": "WAITING_PARTS",
    "Изчаква части": "WAITING_PARTS",
    "Тестване": "TESTING",
}

BATCH_STATUSES = {
    "Издадена партида": "ACTIVE",
    "Частично върната партида": "PARTIALLY_RETURNED",
    "Върната партида": "RETURNED",
}

REPAIR_STATUSES = {
    "Приета": "ACCEPTED",
    "Диагностика": "DIAGNOSIS",
    "Чака одобрение": "WAITING_APPROVAL",
    "Чака части": "WAITING_PARTS",
    "В ремонт": "REPAIRING",
    "Тестване": "TESTING",
    "Завършена": "COMPLETED",
}

PART_REQUEST_STATUSES = {
    "Чернова": "DRAFT",
    "Изпратена": "SUBMITTED",
    "Подадена": "SUBMITTED",
    "Чака одобрение": "WAITING_APPROVAL",
    "Изчакване на одобрение": "WAITING_APPROVAL",
    "Одобрена": "APPROVED",
    "Отхвърлена": "REJECTED",
    "Поръчана": "ORDERED",
    "Частично доставена": "PARTIALLY_DELIVERED",
    "Доставена": "DELIVERED",
    "Отказана": "CANCELLED",
}

PART_REQUEST_PRIORITIES = {
    "Нисък": "LOW",
    "Нормален": "NORMAL",
    "Спешен": "URGENT",
}


def _replace_values(table: str, column: str, mapping: dict[str, str]) -> None:
    bind = op.get_bind()
    statement = sa.text(
        f"UPDATE {table} SET {column} = :new_value WHERE {column} = :old_value"
    )
    for old_value, new_value in mapping.items():
        bind.execute(
            statement, {"old_value": old_value, "new_value": new_value}
        )


def _reverse(mapping: dict[str, str]) -> dict[str, str]:
    # Prefer the first historical Bulgarian spelling when aliases exist.
    return {new_value: old_value for old_value, new_value in reversed(mapping.items())}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "preferred_language" not in user_columns:
        op.add_column(
            "users",
            sa.Column(
                "preferred_language",
                sa.String(length=2),
                nullable=False,
                server_default="bg",
            ),
        )

    _replace_values("machines", "status", MACHINE_STATUSES)
    _replace_values("transfer_protocols", "previous_status", MACHINE_STATUSES)
    _replace_values("transfer_batches", "status", BATCH_STATUSES)
    _replace_values("repairs", "status", REPAIR_STATUSES)
    _replace_values("part_requests", "status", PART_REQUEST_STATUSES)
    _replace_values("part_requests", "priority", PART_REQUEST_PRIORITIES)


def downgrade() -> None:
    _replace_values("machines", "status", _reverse(MACHINE_STATUSES))
    _replace_values(
        "transfer_protocols", "previous_status", _reverse(MACHINE_STATUSES)
    )
    _replace_values("transfer_batches", "status", _reverse(BATCH_STATUSES))
    _replace_values("repairs", "status", _reverse(REPAIR_STATUSES))
    _replace_values(
        "part_requests", "status", _reverse(PART_REQUEST_STATUSES)
    )
    _replace_values(
        "part_requests", "priority", _reverse(PART_REQUEST_PRIORITIES)
    )

    inspector = sa.inspect(op.get_bind())
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "preferred_language" in user_columns:
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("preferred_language")
