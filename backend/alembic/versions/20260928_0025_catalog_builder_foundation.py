"""Add empty, isolated Catalog Builder foundation tables.

Revision ID: 20260928_0025
Revises: 20260924_0024
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0025"
down_revision = "20260924_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical revision 0001 invokes Base.metadata.create_all. On a fresh
    # install it may already have created tables from this application's model;
    # an existing 0024 installation has none. Support both paths explicitly.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "catalog_definitions" not in existing:
        op.create_table(
            "catalog_definitions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("code", sa.String(80), nullable=False, unique=True),
            sa.Column("asset_category_id", sa.Integer(), sa.ForeignKey("asset_categories.id"), nullable=False),
            sa.Column("name_bg", sa.String(255), nullable=False),
            sa.Column("name_en", sa.String(255), nullable=False),
            sa.Column("name_ru", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("manufacturer", sa.String(255), nullable=True),
            sa.Column("model_reference", sa.String(255), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_catalog_definitions_asset_category_id", "catalog_definitions", ["asset_category_id"])
    if "catalog_revisions" not in existing:
        op.create_table(
            "catalog_revisions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("catalog_id", sa.Integer(), sa.ForeignKey("catalog_definitions.id"), nullable=False),
            sa.Column("revision_code", sa.String(80), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
            sa.Column("change_note", sa.Text(), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("published_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("catalog_id", "revision_code", name="uq_catalog_revision_code"),
            sa.CheckConstraint("status IN ('DRAFT', 'PUBLISHED', 'RETIRED')", name="ck_catalog_revision_status"),
        )
        op.create_index("ix_catalog_revisions_catalog_id", "catalog_revisions", ["catalog_id"])
    if "catalog_asset_bindings" not in existing:
        op.create_table(
            "catalog_asset_bindings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("catalog_id", sa.Integer(), sa.ForeignKey("catalog_definitions.id"), nullable=False),
            sa.Column("machine_id", sa.Integer(), sa.ForeignKey("machines.id"), nullable=False, unique=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_catalog_asset_bindings_catalog_id", "catalog_asset_bindings", ["catalog_id"])


def downgrade() -> None:
    # Do not silently discard Builder workspaces on an operator rollback.
    bind = op.get_bind()
    for name in ("catalog_revisions", "catalog_asset_bindings", "catalog_definitions"):
        if bind.scalar(sa.text(f"SELECT count(*) FROM {name}")):
            raise RuntimeError("Cannot downgrade: Catalog Builder workspaces contain data")
    # Only empty Builder schema is removed; V2 and historical tables are untouched.
    op.drop_index("ix_catalog_asset_bindings_catalog_id", table_name="catalog_asset_bindings")
    op.drop_table("catalog_asset_bindings")
    op.drop_index("ix_catalog_revisions_catalog_id", table_name="catalog_revisions")
    op.drop_table("catalog_revisions")
    op.drop_index("ix_catalog_definitions_asset_category_id", table_name="catalog_definitions")
    op.drop_table("catalog_definitions")
