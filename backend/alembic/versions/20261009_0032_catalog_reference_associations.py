"""Add audited supplemental references; no business data updates.

Revision ID: 20261009_0032
Revises: 20261001_0031
"""

import sqlalchemy as sa
from alembic import op

revision = "20261009_0032"
down_revision = "20261001_0031"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "catalog_reference_associations" not in existing:
        op.create_table("catalog_reference_associations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("machine_id", sa.Integer(), sa.ForeignKey("machines.id"), nullable=False),
            sa.Column("source_id", sa.String(120), nullable=False),
            sa.Column("source_revision", sa.String(255), nullable=False),
            sa.Column("builder_revision_id", sa.Integer(), sa.ForeignKey("catalog_revisions.id")),
            sa.Column("scheme_id", sa.Integer(), sa.ForeignKey("catalog_visual_sources.id"), nullable=False),
            sa.Column("parts_list_id", sa.Integer(), sa.ForeignKey("catalog_visual_sources.id"), nullable=False),
            sa.Column("confirmed_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=False),
            sa.Column("revoked_by_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("revoked_at", sa.DateTime()),
            sa.Column("revoke_reason", sa.Text()))
        for column in ("machine_id", "source_id"):
            op.create_index(f"ix_catalog_reference_associations_{column}",
                            "catalog_reference_associations", [column])
        op.create_index("uq_catalog_reference_active", "catalog_reference_associations",
            ["machine_id", "scheme_id", "parts_list_id"], unique=True,
            postgresql_where=sa.text("revoked_at IS NULL"), sqlite_where=sa.text("revoked_at IS NULL"))
    if "catalog_reference_parts" not in existing:
        op.create_table("catalog_reference_parts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("association_id", sa.Integer(), sa.ForeignKey("catalog_reference_associations.id"), nullable=False),
            sa.Column("part_id", sa.Integer(), sa.ForeignKey("part_catalog.id"), nullable=False),
            sa.UniqueConstraint("association_id", "part_id", name="uq_catalog_reference_part"))
        for column in ("association_id", "part_id"):
            op.create_index(f"ix_catalog_reference_parts_{column}", "catalog_reference_parts", [column])


def downgrade():
    connection = op.get_bind()
    existing = set(sa.inspect(connection).get_table_names())
    tables = ("catalog_reference_parts", "catalog_reference_associations")
    for name in tables:
        if name in existing and connection.scalar(sa.select(sa.func.count()).select_from(sa.table(name))):
            raise RuntimeError("Audited reference history cannot be discarded by downgrade")
    for name in tables:
        if name in existing:
            op.drop_table(name)
