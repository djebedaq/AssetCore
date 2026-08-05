"""verified part catalog provenance and decimal quantities

Revision ID: 20260805_0012
Revises: 20260805_0011
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260805_0012"
down_revision = "20260805_0011"
branch_labels = None
depends_on = None


def _columns() -> dict[str, dict]:
    return {item["name"]: item for item in sa.inspect(op.get_bind()).get_columns("part_catalog")}


def _indexes() -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("part_catalog")}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns()
    quantity_type = columns["quantity"]["type"]
    if isinstance(quantity_type, sa.Integer):
        if bind.dialect.name == "postgresql":
            op.alter_column(
                "part_catalog", "quantity", existing_type=sa.Integer(),
                type_=sa.Float(), existing_nullable=True,
                postgresql_using="quantity::double precision",
            )
        else:
            with op.batch_alter_table("part_catalog") as batch:
                batch.alter_column(
                    "quantity", existing_type=sa.Integer(),
                    type_=sa.Float(), existing_nullable=True,
                )

    additions = [
        ("source_figure", sa.Column("source_figure", sa.String(length=255), nullable=True)),
        ("diagram_page", sa.Column("diagram_page", sa.Integer(), nullable=True)),
        ("source_version", sa.Column("source_version", sa.String(length=255), nullable=True)),
        ("source_document_sha256", sa.Column("source_document_sha256", sa.String(length=64), nullable=True)),
        ("verification_status", sa.Column("verification_status", sa.String(length=50), server_default="UNVERIFIED", nullable=False)),
        ("replaced_by_part_number", sa.Column("replaced_by_part_number", sa.String(length=120), nullable=True)),
    ]
    missing = [(name, column) for name, column in additions if name not in _columns()]
    if missing:
        with op.batch_alter_table("part_catalog") as batch:
            for _, column in missing:
                batch.add_column(column)

    if "ix_part_catalog_source_document_sha256" not in _indexes():
        op.create_index(
            "ix_part_catalog_source_document_sha256",
            "part_catalog", ["source_document_sha256"], unique=False,
        )


def downgrade() -> None:
    if "ix_part_catalog_source_document_sha256" in _indexes():
        op.drop_index("ix_part_catalog_source_document_sha256", table_name="part_catalog")
    removable = [
        "replaced_by_part_number", "verification_status", "source_document_sha256",
        "source_version", "diagram_page", "source_figure",
    ]
    present = [name for name in removable if name in _columns()]
    if present:
        with op.batch_alter_table("part_catalog") as batch:
            for name in present:
                batch.drop_column(name)
    bind = op.get_bind()
    columns = _columns()
    if "quantity" in columns and isinstance(columns["quantity"]["type"], sa.Float):
        if bind.dialect.name == "postgresql":
            op.alter_column(
                "part_catalog", "quantity", existing_type=sa.Float(),
                type_=sa.Integer(), existing_nullable=True,
                postgresql_using="round(quantity)::integer",
            )
        else:
            with op.batch_alter_table("part_catalog") as batch:
                batch.alter_column(
                    "quantity", existing_type=sa.Float(),
                    type_=sa.Integer(), existing_nullable=True,
                )
