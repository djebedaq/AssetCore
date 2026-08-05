"""Safe cancellation for pending transfer batches.

Revision ID: 20260805_0009
Revises: 20260805_0008
"""
from alembic import op
import sqlalchemy as sa

revision = "20260805_0009"
down_revision = "20260805_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("transfer_batches")}
    indexes = {item["name"] for item in inspector.get_indexes("transfer_batches")}
    foreign_keys = {item.get("name") for item in inspector.get_foreign_keys("transfer_batches")}
    with op.batch_alter_table("transfer_batches") as batch:
        if "cancelled_at" not in columns:
            batch.add_column(sa.Column("cancelled_at", sa.DateTime(), nullable=True))
        if "cancelled_by_id" not in columns:
            batch.add_column(sa.Column("cancelled_by_id", sa.Integer(), nullable=True))
        if "cancellation_reason" not in columns:
            batch.add_column(sa.Column("cancellation_reason", sa.Text(), nullable=True))
        if "ix_transfer_batches_cancelled_by_id" not in indexes:
            batch.create_index(
                "ix_transfer_batches_cancelled_by_id", ["cancelled_by_id"], unique=False
            )
        if "fk_transfer_batches_cancelled_by_id_users" not in foreign_keys:
            batch.create_foreign_key(
                "fk_transfer_batches_cancelled_by_id_users",
                "users",
                ["cancelled_by_id"],
                ["id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("transfer_batches")}
    indexes = {item["name"] for item in inspector.get_indexes("transfer_batches")}
    foreign_keys = {item.get("name") for item in inspector.get_foreign_keys("transfer_batches")}
    with op.batch_alter_table("transfer_batches") as batch:
        if "fk_transfer_batches_cancelled_by_id_users" in foreign_keys:
            batch.drop_constraint("fk_transfer_batches_cancelled_by_id_users", type_="foreignkey")
        if "ix_transfer_batches_cancelled_by_id" in indexes:
            batch.drop_index("ix_transfer_batches_cancelled_by_id")
        for column in ("cancellation_reason", "cancelled_by_id", "cancelled_at"):
            if column in columns:
                batch.drop_column(column)
