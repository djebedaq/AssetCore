"""Add guarded bulk transfer batches and stored protocol documents.

Revision ID: 20260731_0001
Revises:
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260731_0001"
down_revision = None
branch_labels = None
depends_on = None


TRANSFER_COLUMNS = [
    sa.Column("batch_id", sa.Integer(), sa.ForeignKey("transfer_batches.id", name="fk_transfer_protocols_batch_id"), nullable=True),
    sa.Column("is_active", sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column("previous_status", sa.String(length=80), nullable=True),
    sa.Column("previous_location_id", sa.Integer(), sa.ForeignKey("locations.id", name="fk_transfer_protocols_previous_location_id"), nullable=True),
    sa.Column("issue_location_id", sa.Integer(), sa.ForeignKey("locations.id", name="fk_transfer_protocols_issue_location_id"), nullable=True),
    sa.Column("return_location_id", sa.Integer(), sa.ForeignKey("locations.id", name="fk_transfer_protocols_return_location_id"), nullable=True),
    sa.Column("return_condition_text", sa.Text(), nullable=True),
    sa.Column("return_result_text", sa.Text(), nullable=True),
    sa.Column("return_notes", sa.Text(), nullable=True),
    sa.Column("returned_by_name", sa.String(length=255), nullable=True),
    sa.Column("return_accepted_by", sa.String(length=255), nullable=True),
    sa.Column("issued_by_id", sa.Integer(), sa.ForeignKey("users.id", name="fk_transfer_protocols_issued_by_id"), nullable=True),
    sa.Column("returned_by_id", sa.Integer(), sa.ForeignKey("users.id", name="fk_transfer_protocols_returned_by_id"), nullable=True),
    sa.Column("issued_at", sa.DateTime(), nullable=True),
    sa.Column("returned_at", sa.DateTime(), nullable=True),
]


def _index_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {item["name"] for item in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()

    # The RC previously used create_all without a migration stamp. Creating only
    # missing tables first lets this revision upgrade both empty and legacy DBs.
    import app.models  # noqa: F401
    from app.database import Base

    Base.metadata.create_all(bind=bind)
    inspector = sa.inspect(bind)

    transfer_columns = {
        column["name"] for column in inspector.get_columns("transfer_protocols")
    }
    missing_transfer_columns = [
        column for column in TRANSFER_COLUMNS if column.name not in transfer_columns
    ]
    if bind.dialect.name == "sqlite" and missing_transfer_columns:
        with op.batch_alter_table("transfer_protocols") as batch_op:
            for column in missing_transfer_columns:
                batch_op.add_column(column)
    else:
        for column in missing_transfer_columns:
            op.add_column("transfer_protocols", column)

    inspector = sa.inspect(bind)
    audit_columns = {column["name"] for column in inspector.get_columns("audit_logs")}
    missing_audit_columns = []
    if "user_id" not in audit_columns:
        missing_audit_columns.append(
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", name="fk_audit_logs_user_id"), nullable=True)
        )
    if "operation_reference" not in audit_columns:
        missing_audit_columns.append(
            sa.Column("operation_reference", sa.String(length=80), nullable=True)
        )
    if bind.dialect.name == "sqlite" and missing_audit_columns:
        with op.batch_alter_table("audit_logs") as batch_op:
            for column in missing_audit_columns:
                batch_op.add_column(column)
    else:
        for column in missing_audit_columns:
            op.add_column("audit_logs", column)

    op.execute(
        sa.text(
            "UPDATE transfer_protocols SET issued_at = created_at "
            "WHERE protocol_type = 'Предаване' AND issued_at IS NULL"
        )
    )
    op.execute(sa.text("UPDATE transfer_protocols SET is_active = false"))
    issued_machine_ids = bind.execute(
        sa.text(
            "SELECT id FROM machines WHERE status IN ('Издадена', 'В употреба')"
        )
    ).scalars()
    for machine_id in issued_machine_ids:
        transfer_id = bind.execute(
            sa.text(
                "SELECT id FROM transfer_protocols "
                "WHERE machine_id = :machine_id AND protocol_type = 'Предаване' "
                "ORDER BY created_at DESC, id DESC"
            ),
            {"machine_id": machine_id},
        ).scalar()
        if transfer_id is not None:
            bind.execute(
                sa.text(
                    "UPDATE transfer_protocols SET is_active = true WHERE id = :id"
                ),
                {"id": transfer_id},
            )

    inspector = sa.inspect(bind)
    transfer_indexes = _index_names(inspector, "transfer_protocols")
    regular_indexes = {
        "ix_transfer_protocols_batch_id": ["batch_id"],
        "ix_transfer_protocols_is_active": ["is_active"],
        "ix_transfer_protocols_issued_by_id": ["issued_by_id"],
        "ix_transfer_protocols_returned_by_id": ["returned_by_id"],
    }
    for name, columns in regular_indexes.items():
        if name not in transfer_indexes:
            op.create_index(name, "transfer_protocols", columns, unique=False)
    if "uq_transfer_protocols_active_machine" not in transfer_indexes:
        if bind.dialect.name == "postgresql":
            op.create_index(
                "uq_transfer_protocols_active_machine",
                "transfer_protocols",
                ["machine_id"],
                unique=True,
                postgresql_where=sa.text("is_active IS TRUE"),
            )
        else:
            op.create_index(
                "uq_transfer_protocols_active_machine",
                "transfer_protocols",
                ["machine_id"],
                unique=True,
                sqlite_where=sa.text("is_active = 1"),
            )

    inspector = sa.inspect(bind)
    audit_indexes = _index_names(inspector, "audit_logs")
    if "ix_audit_logs_user_id" not in audit_indexes:
        op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    if "ix_audit_logs_operation_reference" not in audit_indexes:
        op.create_index(
            "ix_audit_logs_operation_reference",
            "audit_logs",
            ["operation_reference"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "protocol_documents" in inspector.get_table_names():
        op.drop_table("protocol_documents")
    if "transfer_batches" in inspector.get_table_names():
        # Foreign keys from transfer_protocols are removed below by batch mode.
        pass

    transfer_indexes = _index_names(sa.inspect(bind), "transfer_protocols")
    for name in [
        "uq_transfer_protocols_active_machine",
        "ix_transfer_protocols_batch_id",
        "ix_transfer_protocols_is_active",
        "ix_transfer_protocols_issued_by_id",
        "ix_transfer_protocols_returned_by_id",
    ]:
        if name in transfer_indexes:
            op.drop_index(name, table_name="transfer_protocols")

    transfer_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("transfer_protocols")
    }
    with op.batch_alter_table("transfer_protocols") as batch_op:
        for column in reversed(TRANSFER_COLUMNS):
            if column.name in transfer_columns:
                batch_op.drop_column(column.name)

    if "transfer_batches" in sa.inspect(bind).get_table_names():
        op.drop_table("transfer_batches")

    audit_indexes = _index_names(sa.inspect(bind), "audit_logs")
    if "ix_audit_logs_operation_reference" in audit_indexes:
        op.drop_index("ix_audit_logs_operation_reference", table_name="audit_logs")
    if "ix_audit_logs_user_id" in audit_indexes:
        op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    audit_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("audit_logs")
    }
    with op.batch_alter_table("audit_logs") as batch_op:
        if "operation_reference" in audit_columns:
            batch_op.drop_column("operation_reference")
        if "user_id" in audit_columns:
            batch_op.drop_column("user_id")
