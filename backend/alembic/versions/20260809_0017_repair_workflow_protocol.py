"""repair workflow durations and participant idempotency

Revision ID: 20260809_0017
Revises: 20260808_0016
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260809_0017"
down_revision = "20260808_0016"
branch_labels = None
depends_on = None


def _index_names(table_name: str) -> set[str]:
    return {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_indexes(table_name)
        if item.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    repair_columns = {column["name"] for column in inspector.get_columns("repairs")}
    with op.batch_alter_table("repairs") as batch_op:
        if "required_parts_text" not in repair_columns:
            batch_op.add_column(sa.Column("required_parts_text", sa.Text(), nullable=True))
        for name in ("diagnosis_minutes", "repair_minutes", "testing_minutes"):
            if name not in repair_columns:
                batch_op.add_column(sa.Column(name, sa.Integer(), nullable=True))
    check_names = {
        item["name"]
        for item in sa.inspect(bind).get_check_constraints("repairs")
        if item.get("name")
    }
    duration_checks = {
        "ck_repairs_diagnosis_minutes_nonnegative": "diagnosis_minutes IS NULL OR diagnosis_minutes >= 0",
        "ck_repairs_repair_minutes_nonnegative": "repair_minutes IS NULL OR repair_minutes >= 0",
        "ck_repairs_testing_minutes_nonnegative": "testing_minutes IS NULL OR testing_minutes >= 0",
    }
    with op.batch_alter_table("repairs") as batch_op:
        for name, expression in duration_checks.items():
            if name not in check_names:
                batch_op.create_check_constraint(name, expression)

    # Historical participant snapshots stay byte-for-byte unchanged. The key is
    # populated only for new mutations, so a legacy duplicate can never make an
    # otherwise safe deployment fail.
    participant_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("repair_participants")
    }
    if "identity_key" not in participant_columns:
        with op.batch_alter_table("repair_participants") as batch_op:
            batch_op.add_column(sa.Column("identity_key", sa.String(length=320), nullable=True))
    if "uq_repair_participants_identity_key" not in _index_names("repair_participants"):
        op.create_index(
            "uq_repair_participants_identity_key",
            "repair_participants",
            ["repair_id", "identity_key"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "uq_repair_participants_identity_key" in _index_names("repair_participants"):
        op.drop_index(
            "uq_repair_participants_identity_key",
            table_name="repair_participants",
        )
    participant_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("repair_participants")
    }
    if "identity_key" in participant_columns:
        with op.batch_alter_table("repair_participants") as batch_op:
            batch_op.drop_column("identity_key")
    repair_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("repairs")
    }
    repair_check_names = {
        item["name"]
        for item in sa.inspect(bind).get_check_constraints("repairs")
        if item.get("name")
    }
    with op.batch_alter_table("repairs") as batch_op:
        for name in (
            "ck_repairs_testing_minutes_nonnegative",
            "ck_repairs_repair_minutes_nonnegative",
            "ck_repairs_diagnosis_minutes_nonnegative",
        ):
            if name in repair_check_names:
                batch_op.drop_constraint(name, type_="check")
        for name in ("testing_minutes", "repair_minutes", "diagnosis_minutes"):
            if name in repair_columns:
                batch_op.drop_column(name)
        if "required_parts_text" in repair_columns:
            batch_op.drop_column("required_parts_text")
