"""Add isolated draft part and exact spare-list-page staging.

Revision ID: 20260928_0027
Revises: 20260928_0026
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0027"
down_revision = "20260928_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Initial migration creates current metadata for fresh installations.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "catalog_revision_parts" not in existing:
        op.create_table(
            "catalog_revision_parts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("assembly_id", sa.Integer(), sa.ForeignKey("catalog_revision_assemblies.id"), nullable=False),
            sa.Column("position", sa.String(80), nullable=False),
            sa.Column("part_number", sa.String(120), nullable=False),
            sa.Column("name_bg", sa.String(255)), sa.Column("name_en", sa.String(255)),
            sa.Column("name_ru", sa.String(255)), sa.Column("description", sa.Text()),
            sa.Column("description_2", sa.Text()), sa.Column("quantity", sa.Numeric(14, 4)),
            sa.Column("quantity_raw", sa.String(120)), sa.Column("unit", sa.String(80)),
            sa.Column("manufacturer", sa.String(255)), sa.Column("category", sa.String(255)),
            sa.Column("replaced_by_part_number", sa.String(120)),
            sa.Column("alternative_part_number", sa.String(120)),
            sa.Column("technical_specification", sa.Text()), sa.Column("technical_notes", sa.Text()),
            sa.Column("supplier", sa.String(255)), sa.Column("supplier_code", sa.String(120)),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("assembly_id", "position", "part_number", name="uq_catalog_revision_part_identity"),
            sa.CheckConstraint("quantity IS NULL OR quantity >= 0", name="ck_catalog_revision_part_quantity"),
        )
        op.create_index("ix_catalog_revision_parts_assembly_id", "catalog_revision_parts", ["assembly_id"])
    if "catalog_revision_part_page_maps" not in existing:
        op.create_table(
            "catalog_revision_part_page_maps",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("part_id", sa.Integer(), sa.ForeignKey("catalog_revision_parts.id"), nullable=False),
            sa.Column("visual_page_id", sa.Integer(), sa.ForeignKey("catalog_revision_visual_pages.id"), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("part_id", "visual_page_id", name="uq_catalog_revision_part_page_map"),
        )
        op.create_index("ix_catalog_revision_part_page_maps_part_id", "catalog_revision_part_page_maps", ["part_id"])
        op.create_index("ix_catalog_revision_part_page_maps_visual_page_id", "catalog_revision_part_page_maps", ["visual_page_id"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("catalog_revision_part_page_maps", "catalog_revision_parts"):
        if bind.scalar(sa.text(f"SELECT count(*) FROM {table}")):
            raise RuntimeError("Cannot downgrade: Catalog Builder part staging contains data")
    op.drop_index("ix_catalog_revision_part_page_maps_visual_page_id", table_name="catalog_revision_part_page_maps")
    op.drop_index("ix_catalog_revision_part_page_maps_part_id", table_name="catalog_revision_part_page_maps")
    op.drop_table("catalog_revision_part_page_maps")
    op.drop_index("ix_catalog_revision_parts_assembly_id", table_name="catalog_revision_parts")
    op.drop_table("catalog_revision_parts")
