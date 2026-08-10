"""simplify active repair workflow to four stages

Revision ID: 20260810_0018
Revises: 20260809_0017
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260810_0018"
down_revision = "20260809_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    repair_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("repairs")
    }
    if "diagnostic_cleaning" not in repair_columns:
        with op.batch_alter_table("repairs") as batch_op:
            batch_op.add_column(
                sa.Column("diagnostic_cleaning", sa.Text(), nullable=True)
            )

    participant_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("repair_participants")
    }
    if "minutes_worked" not in participant_columns:
        with op.batch_alter_table("repair_participants") as batch_op:
            batch_op.add_column(
                sa.Column("minutes_worked", sa.Integer(), nullable=True)
            )

    participant_checks = {
        item["name"]
        for item in sa.inspect(bind).get_check_constraints("repair_participants")
        if item.get("name")
    }
    if "ck_repair_participants_minutes_positive" not in participant_checks:
        with op.batch_alter_table("repair_participants") as batch_op:
            batch_op.create_check_constraint(
                "ck_repair_participants_minutes_positive",
                "minutes_worked IS NULL OR minutes_worked > 0",
            )

    # Preserve every historical event and payload. Only active repair rows are
    # normalized so the retired branches cannot block the four-stage wizard.
    bind.execute(
        sa.text(
            "UPDATE repairs SET status = 'DIAGNOSIS' "
            "WHERE status = 'WAITING_APPROVAL'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE repairs SET status = CASE "
            "WHEN NULLIF(TRIM(COALESCE(work_performed, '')), '') IS NOT NULL "
            "OR COALESCE(repair_minutes, 0) > 0 "
            "THEN 'REPAIRING' ELSE 'DIAGNOSIS' END "
            "WHERE status = 'WAITING_PARTS'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE repairs SET status = 'REPAIRING' WHERE status = 'TESTING'"
        )
    )


def downgrade() -> None:
    # Retired statuses cannot be reconstructed without inventing history. The
    # schema downgrade is reversible, while normalized operational statuses are
    # deliberately kept as DIAGNOSIS/REPAIRING.
    bind = op.get_bind()
    participant_checks = {
        item["name"]
        for item in sa.inspect(bind).get_check_constraints("repair_participants")
        if item.get("name")
    }
    with op.batch_alter_table("repair_participants") as batch_op:
        if "ck_repair_participants_minutes_positive" in participant_checks:
            batch_op.drop_constraint(
                "ck_repair_participants_minutes_positive", type_="check"
            )
        participant_columns = {
            column["name"]
            for column in sa.inspect(bind).get_columns("repair_participants")
        }
        if "minutes_worked" in participant_columns:
            batch_op.drop_column("minutes_worked")

    repair_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("repairs")
    }
    if "diagnostic_cleaning" in repair_columns:
        with op.batch_alter_table("repairs") as batch_op:
            batch_op.drop_column("diagnostic_cleaning")
