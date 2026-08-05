"""Add issue and return condition checklists.

Revision ID: 20260805_0008
Revises: 20260805_0007
"""
from alembic import op
import sqlalchemy as sa

revision = "20260805_0008"
down_revision = "20260805_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("transfer_protocols")}
    missing = []
    if "issue_checklist" not in columns:
        missing.append(sa.Column("issue_checklist", sa.JSON(), nullable=True))
    if "return_checklist" not in columns:
        missing.append(sa.Column("return_checklist", sa.JSON(), nullable=True))
    if missing:
        with op.batch_alter_table("transfer_protocols") as batch_op:
            for column in missing:
                batch_op.add_column(column)


def downgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("transfer_protocols")}
    with op.batch_alter_table("transfer_protocols") as batch_op:
        if "return_checklist" in columns:
            batch_op.drop_column("return_checklist")
        if "issue_checklist" in columns:
            batch_op.drop_column("issue_checklist")
