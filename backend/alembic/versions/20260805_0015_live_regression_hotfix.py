"""live regression hotfix guards

Revision ID: 20260805_0015
Revises: 20260805_0014
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260805_0015"
down_revision = "20260805_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "repair_participants" not in inspector.get_table_names():
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
    # Data-safe hotfix: never remove a production participant table on downgrade.
    pass
