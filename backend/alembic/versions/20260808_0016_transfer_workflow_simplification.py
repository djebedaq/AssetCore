"""simplify operational transfer and repair workflow

Revision ID: 20260808_0016
Revises: 20260805_0015
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260808_0016"
down_revision = "20260805_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    repair_columns = {column["name"] for column in inspector.get_columns("repairs")}

    with op.batch_alter_table("repairs") as batch_op:
        if "source_return_transfer_id" not in repair_columns:
            batch_op.add_column(
                sa.Column(
                    "source_return_transfer_id",
                    sa.Integer(),
                    sa.ForeignKey(
                        "transfer_protocols.id",
                        name="fk_repairs_source_return_transfer_id",
                    ),
                    nullable=True,
                )
            )
        if "source_return_document_id" not in repair_columns:
            batch_op.add_column(
                sa.Column(
                    "source_return_document_id",
                    sa.Integer(),
                    sa.ForeignKey(
                        "official_documents.id",
                        name="fk_repairs_source_return_document_id",
                    ),
                    nullable=True,
                )
            )
        if "source_return_batch_id" not in repair_columns:
            batch_op.add_column(
                sa.Column(
                    "source_return_batch_id",
                    sa.Integer(),
                    sa.ForeignKey(
                        "transfer_batches.id",
                        name="fk_repairs_source_return_batch_id",
                    ),
                    nullable=True,
                )
            )

    inspector = sa.inspect(bind)
    repair_indexes = {index["name"] for index in inspector.get_indexes("repairs")}
    if "ix_repairs_source_return_transfer_id" not in repair_indexes:
        op.create_index(
            "ix_repairs_source_return_transfer_id",
            "repairs",
            ["source_return_transfer_id"],
            unique=True,
        )
    if "ix_repairs_source_return_document_id" not in repair_indexes:
        op.create_index(
            "ix_repairs_source_return_document_id",
            "repairs",
            ["source_return_document_id"],
            unique=False,
        )
    if "ix_repairs_source_return_batch_id" not in repair_indexes:
        op.create_index(
            "ix_repairs_source_return_batch_id",
            "repairs",
            ["source_return_batch_id"],
            unique=False,
        )

    workshop_id = bind.execute(
        sa.text("SELECT id FROM locations WHERE name = :name"), {"name": "Цех"}
    ).scalar_one_or_none()
    if workshop_id is None:
        bind.execute(
            sa.text("INSERT INTO locations (name, is_active) VALUES (:name, :active)"),
            {"name": "Цех", "active": True},
        )
    else:
        bind.execute(
            sa.text("UPDATE locations SET is_active = :active WHERE id = :id"),
            {"active": True, "id": workshop_id},
        )

    # Only current operational state is normalized. Audit, transfer, repair and
    # document snapshots remain immutable and retain their historical values.
    bind.execute(
        sa.text(
            """
            UPDATE machines
            SET status = CASE
                WHEN EXISTS (
                    SELECT 1 FROM transfer_protocols
                    WHERE transfer_protocols.machine_id = machines.id
                      AND transfer_protocols.is_active = :active
                ) THEN 'ISSUED'
                WHEN EXISTS (
                    SELECT 1 FROM repairs
                    WHERE repairs.machine_id = machines.id
                      AND repairs.status <> 'COMPLETED'
                ) THEN 'REPAIR'
                ELSE 'READY'
            END
            """
        ),
        {"active": True},
    )


def downgrade() -> None:
    # Operational statuses cannot be reconstructed safely, so downgrade does
    # not invent previous values. Newly added relational metadata is reversible.
    inspector = sa.inspect(op.get_bind())
    repair_indexes = {index["name"] for index in inspector.get_indexes("repairs")}
    for index_name in (
        "ix_repairs_source_return_batch_id",
        "ix_repairs_source_return_document_id",
        "ix_repairs_source_return_transfer_id",
    ):
        if index_name in repair_indexes:
            op.drop_index(index_name, table_name="repairs")

    repair_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("repairs")
    }
    with op.batch_alter_table("repairs") as batch_op:
        for column_name in (
            "source_return_batch_id",
            "source_return_document_id",
            "source_return_transfer_id",
        ):
            if column_name in repair_columns:
                batch_op.drop_column(column_name)
