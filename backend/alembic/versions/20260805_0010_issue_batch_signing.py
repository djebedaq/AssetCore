"""Bind one signing act to all issue protocols in a transfer batch.

Revision ID: 20260805_0010
Revises: 20260805_0009
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260805_0010"
down_revision = "20260805_0009"
branch_labels = None
depends_on = None


def _names(items: list[dict]) -> set[str]:
    return {item.get("name") for item in items if item.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    batch_columns = {item["name"] for item in inspector.get_columns("transfer_batches")}
    batch_indexes = _names(inspector.get_indexes("transfer_batches"))
    batch_foreign_keys = _names(inspector.get_foreign_keys("transfer_batches"))
    batch_uniques = _names(inspector.get_unique_constraints("transfer_batches"))
    with op.batch_alter_table("transfer_batches") as batch:
        if "issue_manifest" not in batch_columns:
            batch.add_column(sa.Column("issue_manifest", sa.JSON(), nullable=True))
        if "issue_manifest_sha256" not in batch_columns:
            batch.add_column(sa.Column("issue_manifest_sha256", sa.String(length=64), nullable=True))
        if "issue_signing_document_id" not in batch_columns:
            batch.add_column(sa.Column("issue_signing_document_id", sa.Integer(), nullable=True))
        if "issue_signing_status" not in batch_columns:
            batch.add_column(sa.Column("issue_signing_status", sa.String(length=40), nullable=True))
        if "fk_transfer_batches_issue_signing_document" not in batch_foreign_keys:
            batch.create_foreign_key(
                "fk_transfer_batches_issue_signing_document",
                "official_documents",
                ["issue_signing_document_id"],
                ["id"],
            )
        if "uq_transfer_batches_issue_signing_document" not in batch_uniques:
            batch.create_unique_constraint(
                "uq_transfer_batches_issue_signing_document",
                ["issue_signing_document_id"],
            )
        if "ix_transfer_batches_issue_manifest_sha256" not in batch_indexes:
            batch.create_index(
                "ix_transfer_batches_issue_manifest_sha256",
                ["issue_manifest_sha256"],
                unique=False,
            )
        if "ix_transfer_batches_issue_signing_status" not in batch_indexes:
            batch.create_index(
                "ix_transfer_batches_issue_signing_status",
                ["issue_signing_status"],
                unique=False,
            )

    inspector = sa.inspect(bind)
    signature_columns = {item["name"] for item in inspector.get_columns("document_signatures")}
    signature_indexes = _names(inspector.get_indexes("document_signatures"))
    signature_foreign_keys = _names(inspector.get_foreign_keys("document_signatures"))
    with op.batch_alter_table("document_signatures") as batch:
        if "source_signature_id" not in signature_columns:
            batch.add_column(sa.Column("source_signature_id", sa.Integer(), nullable=True))
        if "batch_manifest_sha256" not in signature_columns:
            batch.add_column(sa.Column("batch_manifest_sha256", sa.String(length=64), nullable=True))
        if "fk_document_signatures_source_signature" not in signature_foreign_keys:
            batch.create_foreign_key(
                "fk_document_signatures_source_signature",
                "document_signatures",
                ["source_signature_id"],
                ["id"],
            )
        if "ix_document_signatures_source_signature_id" not in signature_indexes:
            batch.create_index(
                "ix_document_signatures_source_signature_id",
                ["source_signature_id"],
                unique=False,
            )
        if "ix_document_signatures_batch_manifest_sha256" not in signature_indexes:
            batch.create_index(
                "ix_document_signatures_batch_manifest_sha256",
                ["batch_manifest_sha256"],
                unique=False,
            )

    inspector = sa.inspect(bind)
    signature_indexes = _names(inspector.get_indexes("document_signatures"))
    if "uq_document_signatures_image_sha256" in signature_indexes:
        op.drop_index("uq_document_signatures_image_sha256", table_name="document_signatures")
    if "uq_document_signatures_original_image_sha256" not in signature_indexes:
        op.create_index(
            "uq_document_signatures_original_image_sha256",
            "document_signatures",
            ["image_sha256"],
            unique=True,
            sqlite_where=sa.text("image_sha256 IS NOT NULL AND source_signature_id IS NULL"),
            postgresql_where=sa.text("image_sha256 IS NOT NULL AND source_signature_id IS NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    signature_indexes = _names(inspector.get_indexes("document_signatures"))
    if "uq_document_signatures_original_image_sha256" in signature_indexes:
        op.drop_index(
            "uq_document_signatures_original_image_sha256",
            table_name="document_signatures",
        )
    if "uq_document_signatures_image_sha256" not in signature_indexes:
        op.create_index(
            "uq_document_signatures_image_sha256",
            "document_signatures",
            ["image_sha256"],
            unique=True,
            sqlite_where=sa.text("image_sha256 IS NOT NULL"),
            postgresql_where=sa.text("image_sha256 IS NOT NULL"),
        )

    inspector = sa.inspect(bind)
    signature_columns = {item["name"] for item in inspector.get_columns("document_signatures")}
    signature_indexes = _names(inspector.get_indexes("document_signatures"))
    signature_foreign_keys = _names(inspector.get_foreign_keys("document_signatures"))
    with op.batch_alter_table("document_signatures") as batch:
        if "ix_document_signatures_batch_manifest_sha256" in signature_indexes:
            batch.drop_index("ix_document_signatures_batch_manifest_sha256")
        if "ix_document_signatures_source_signature_id" in signature_indexes:
            batch.drop_index("ix_document_signatures_source_signature_id")
        if "fk_document_signatures_source_signature" in signature_foreign_keys:
            batch.drop_constraint("fk_document_signatures_source_signature", type_="foreignkey")
        if "batch_manifest_sha256" in signature_columns:
            batch.drop_column("batch_manifest_sha256")
        if "source_signature_id" in signature_columns:
            batch.drop_column("source_signature_id")

    inspector = sa.inspect(bind)
    batch_columns = {item["name"] for item in inspector.get_columns("transfer_batches")}
    batch_indexes = _names(inspector.get_indexes("transfer_batches"))
    batch_foreign_keys = _names(inspector.get_foreign_keys("transfer_batches"))
    batch_uniques = _names(inspector.get_unique_constraints("transfer_batches"))
    with op.batch_alter_table("transfer_batches") as batch:
        if "ix_transfer_batches_issue_signing_document_id" in batch_indexes:
            batch.drop_index("ix_transfer_batches_issue_signing_document_id")
        if "ix_transfer_batches_issue_signing_status" in batch_indexes:
            batch.drop_index("ix_transfer_batches_issue_signing_status")
        if "ix_transfer_batches_issue_manifest_sha256" in batch_indexes:
            batch.drop_index("ix_transfer_batches_issue_manifest_sha256")
        if "uq_transfer_batches_issue_signing_document" in batch_uniques:
            batch.drop_constraint("uq_transfer_batches_issue_signing_document", type_="unique")
        if "fk_transfer_batches_issue_signing_document" in batch_foreign_keys:
            batch.drop_constraint("fk_transfer_batches_issue_signing_document", type_="foreignkey")
        for column in (
            "issue_signing_status",
            "issue_signing_document_id",
            "issue_manifest_sha256",
            "issue_manifest",
        ):
            if column in batch_columns:
                batch.drop_column(column)
