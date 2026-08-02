"""Integrate transfer signatures and finalize internal repair documents.

Revision ID: 20260801_0006
Revises: 20260801_0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260801_0006"
down_revision = "20260801_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    def add_column(table: str, column: sa.Column) -> bool:
        if column.name in {item["name"] for item in sa.inspect(bind).get_columns(table)}:
            return False
        op.add_column(table, column)
        return True

    def create_index(name: str, table: str, columns: list[str], **kwargs) -> None:
        if name not in {item["name"] for item in sa.inspect(bind).get_indexes(table)}:
            op.create_index(name, table, columns, **kwargs)

    add_column(
        "transfer_protocols",
        sa.Column("issue_status", sa.String(40), nullable=False, server_default="COMPLETED"),
    )
    add_column("transfer_protocols", sa.Column("return_status", sa.String(40), nullable=True))
    add_column("transfer_protocols", sa.Column("return_requested_at", sa.DateTime(), nullable=True))
    add_column("transfer_protocols", sa.Column("return_next_status", sa.String(80), nullable=True))
    add_column(
        "transfer_protocols", sa.Column("return_previous_status", sa.String(80), nullable=True)
    )
    added_return_location = add_column(
        "transfer_protocols", sa.Column("return_previous_location_id", sa.Integer(), nullable=True)
    )
    add_column(
        "transfer_protocols", sa.Column("handed_over_job_title", sa.String(255), nullable=True)
    )
    add_column(
        "transfer_protocols", sa.Column("handed_over_department", sa.String(255), nullable=True)
    )
    add_column(
        "transfer_protocols", sa.Column("accepted_by_job_title", sa.String(255), nullable=True)
    )
    add_column(
        "transfer_protocols", sa.Column("accepted_by_company", sa.String(255), nullable=True)
    )
    add_column(
        "transfer_protocols", sa.Column("returned_by_job_title", sa.String(255), nullable=True)
    )
    add_column(
        "transfer_protocols", sa.Column("returned_by_company", sa.String(255), nullable=True)
    )
    add_column(
        "transfer_protocols", sa.Column("return_accepted_job_title", sa.String(255), nullable=True)
    )
    add_column(
        "transfer_protocols", sa.Column("return_accepted_department", sa.String(255), nullable=True)
    )
    create_index("ix_transfer_protocols_issue_status", "transfer_protocols", ["issue_status"])
    create_index("ix_transfer_protocols_return_status", "transfer_protocols", ["return_status"])
    if bind.dialect.name != "sqlite" and added_return_location:
        op.create_foreign_key(
            "fk_transfer_protocols_return_previous_location_id_locations",
            "transfer_protocols",
            "locations",
            ["return_previous_location_id"],
            ["id"],
        )

    op.execute(
        "UPDATE transfer_protocols SET return_status = 'COMPLETED' " "WHERE returned_at IS NOT NULL"
    )

    add_column(
        "external_signers",
        sa.Column("is_foreign_person", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    add_column("external_signers", sa.Column("name_exception_reason", sa.Text(), nullable=True))

    added_template_version = add_column(
        "official_document_versions", sa.Column("template_version_id", sa.Integer(), nullable=True)
    )
    add_column(
        "official_document_versions", sa.Column("signing_sha256", sa.String(64), nullable=True)
    )
    create_index(
        "ix_official_document_versions_template_version_id",
        "official_document_versions",
        ["template_version_id"],
    )
    create_index(
        "ix_official_document_versions_signing_sha256",
        "official_document_versions",
        ["signing_sha256"],
    )
    if bind.dialect.name != "sqlite" and added_template_version:
        op.create_foreign_key(
            "fk_official_document_versions_template_version_id",
            "official_document_versions",
            "document_template_versions",
            ["template_version_id"],
            ["id"],
        )

    add_column("document_signatures", sa.Column("image_sha256", sa.String(64), nullable=True))
    create_index(
        "ix_document_signatures_image_sha256",
        "document_signatures",
        ["image_sha256"],
    )
    create_index(
        "uq_document_signatures_image_sha256",
        "document_signatures",
        ["image_sha256"],
        unique=True,
        sqlite_where=sa.text("image_sha256 IS NOT NULL"),
        postgresql_where=sa.text("image_sha256 IS NOT NULL"),
    )

    # Repairs are internal records. Existing rows are retained for historical
    # configuration traceability but are no longer active signing requirements.
    op.execute(
        "UPDATE signature_slots SET is_active = false, required = false "
        "WHERE document_type = 'REPAIR_PROTOCOL'"
    )
    op.execute(
        "UPDATE signature_slots SET sequence = 1 "
        "WHERE document_type = 'TRANSFER_ISSUE' AND code = 'ACCEPTANCE'"
    )
    op.execute(
        "UPDATE signature_slots SET sequence = 2 "
        "WHERE document_type = 'TRANSFER_ISSUE' AND code = 'HANDOVER'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE signature_slots SET sequence = 1 "
        "WHERE document_type = 'TRANSFER_ISSUE' AND code = 'HANDOVER'"
    )
    op.execute(
        "UPDATE signature_slots SET sequence = 2 "
        "WHERE document_type = 'TRANSFER_ISSUE' AND code = 'ACCEPTANCE'"
    )
    op.execute(
        "UPDATE signature_slots SET is_active = true, required = true "
        "WHERE document_type = 'REPAIR_PROTOCOL'"
    )

    op.drop_index("uq_document_signatures_image_sha256", table_name="document_signatures")
    op.drop_index("ix_document_signatures_image_sha256", table_name="document_signatures")
    op.drop_column("document_signatures", "image_sha256")

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("official_document_versions", recreate="always") as batch:
            batch.drop_index("ix_official_document_versions_signing_sha256")
            batch.drop_index("ix_official_document_versions_template_version_id")
            batch.drop_column("signing_sha256")
            batch.drop_column("template_version_id")
    else:
        op.drop_constraint(
            "fk_official_document_versions_template_version_id",
            "official_document_versions",
            type_="foreignkey",
        )
        op.drop_index(
            "ix_official_document_versions_signing_sha256", table_name="official_document_versions"
        )
        op.drop_index(
            "ix_official_document_versions_template_version_id",
            table_name="official_document_versions",
        )
        op.drop_column("official_document_versions", "signing_sha256")
        op.drop_column("official_document_versions", "template_version_id")

    op.drop_column("external_signers", "name_exception_reason")
    op.drop_column("external_signers", "is_foreign_person")

    transfer_columns = (
        "return_accepted_department",
        "return_accepted_job_title",
        "returned_by_company",
        "returned_by_job_title",
        "accepted_by_company",
        "accepted_by_job_title",
        "handed_over_department",
        "handed_over_job_title",
        "return_previous_location_id",
        "return_previous_status",
        "return_next_status",
        "return_status",
        "return_requested_at",
        "issue_status",
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("transfer_protocols", recreate="always") as batch:
            batch.drop_index("ix_transfer_protocols_return_status")
            batch.drop_index("ix_transfer_protocols_issue_status")
            for column in transfer_columns:
                batch.drop_column(column)
    else:
        op.drop_constraint(
            "fk_transfer_protocols_return_previous_location_id_locations",
            "transfer_protocols",
            type_="foreignkey",
        )
        op.drop_index("ix_transfer_protocols_return_status", table_name="transfer_protocols")
        op.drop_index("ix_transfer_protocols_issue_status", table_name="transfer_protocols")
        for column in transfer_columns:
            op.drop_column("transfer_protocols", column)
