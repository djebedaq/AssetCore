"""Bind one signing act to selected return protocols.

Revision ID: 20260805_0011
Revises: 20260805_0010
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260805_0011"
down_revision = "20260805_0010"
branch_labels = None
depends_on = None


def _names(items: list[dict]) -> set[str]:
    return {item.get("name") for item in items if item.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("transfer_batches")}
    indexes = _names(inspector.get_indexes("transfer_batches"))
    foreign_keys = _names(inspector.get_foreign_keys("transfer_batches"))
    uniques = _names(inspector.get_unique_constraints("transfer_batches"))

    with op.batch_alter_table("transfer_batches") as batch:
        if "return_manifest" not in columns:
            batch.add_column(sa.Column("return_manifest", sa.JSON(), nullable=True))
        if "return_manifest_sha256" not in columns:
            batch.add_column(
                sa.Column("return_manifest_sha256", sa.String(length=64), nullable=True)
            )
        if "return_signing_document_id" not in columns:
            batch.add_column(
                sa.Column("return_signing_document_id", sa.Integer(), nullable=True)
            )
        if "return_signing_status" not in columns:
            batch.add_column(
                sa.Column("return_signing_status", sa.String(length=40), nullable=True)
            )
        if "fk_transfer_batches_return_signing_document" not in foreign_keys:
            batch.create_foreign_key(
                "fk_transfer_batches_return_signing_document",
                "official_documents",
                ["return_signing_document_id"],
                ["id"],
            )
        if "uq_transfer_batches_return_signing_document" not in uniques:
            batch.create_unique_constraint(
                "uq_transfer_batches_return_signing_document",
                ["return_signing_document_id"],
            )
        if "ix_transfer_batches_return_manifest_sha256" not in indexes:
            batch.create_index(
                "ix_transfer_batches_return_manifest_sha256",
                ["return_manifest_sha256"],
                unique=False,
            )
        if "ix_transfer_batches_return_signing_status" not in indexes:
            batch.create_index(
                "ix_transfer_batches_return_signing_status",
                ["return_signing_status"],
                unique=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("transfer_batches")}
    indexes = _names(inspector.get_indexes("transfer_batches"))
    foreign_keys = _names(inspector.get_foreign_keys("transfer_batches"))
    uniques = _names(inspector.get_unique_constraints("transfer_batches"))

    with op.batch_alter_table("transfer_batches") as batch:
        if "ix_transfer_batches_return_signing_document_id" in indexes:
            batch.drop_index("ix_transfer_batches_return_signing_document_id")
        if "ix_transfer_batches_return_signing_status" in indexes:
            batch.drop_index("ix_transfer_batches_return_signing_status")
        if "ix_transfer_batches_return_manifest_sha256" in indexes:
            batch.drop_index("ix_transfer_batches_return_manifest_sha256")
        if "uq_transfer_batches_return_signing_document" in uniques:
            batch.drop_constraint(
                "uq_transfer_batches_return_signing_document", type_="unique"
            )
        if "fk_transfer_batches_return_signing_document" in foreign_keys:
            batch.drop_constraint(
                "fk_transfer_batches_return_signing_document", type_="foreignkey"
            )
        for column in (
            "return_signing_status",
            "return_signing_document_id",
            "return_manifest_sha256",
            "return_manifest",
        ):
            if column in columns:
                batch.drop_column(column)
