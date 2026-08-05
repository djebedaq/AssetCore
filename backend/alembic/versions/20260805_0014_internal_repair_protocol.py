"""internal repair protocol participants and immutable snapshots

Revision ID: 20260805_0014
Revises: 20260805_0013
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260805_0014"
down_revision = "20260805_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "repair_participants" in inspector.get_table_names():
        return
    op.create_table(
        "repair_participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repair_id", sa.Integer(), sa.ForeignKey("repairs.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("full_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("job_title_snapshot", sa.String(length=255), nullable=True),
        sa.Column("contribution", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_repair_participants_repair_id", "repair_participants", ["repair_id"], unique=False)
    op.create_index("ix_repair_participants_user_id", "repair_participants", ["user_id"], unique=False)
    op.create_index("ix_repair_participants_created_by_id", "repair_participants", ["created_by_id"], unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "repair_participants" not in inspector.get_table_names():
        return
    for name in ("ix_repair_participants_created_by_id", "ix_repair_participants_user_id", "ix_repair_participants_repair_id"):
        if name in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("repair_participants")}:
            op.drop_index(name, table_name="repair_participants")
    op.drop_table("repair_participants")
