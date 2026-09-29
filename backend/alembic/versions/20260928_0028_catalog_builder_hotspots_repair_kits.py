"""Add draft position hotspots and repair kits without changing live catalog tables.

Revision ID: 20260928_0028
Revises: 20260928_0027
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0028"
down_revision = "20260928_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "catalog_revision_position_hotspots" not in existing:
        op.create_table(
            "catalog_revision_position_hotspots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("visual_page_id", sa.Integer(), sa.ForeignKey("catalog_revision_visual_pages.id"), nullable=False),
            sa.Column("position", sa.String(80), nullable=False),
            sa.Column("x", sa.Float(), nullable=False), sa.Column("y", sa.Float(), nullable=False),
            sa.Column("width", sa.Float(), nullable=False), sa.Column("height", sa.Float(), nullable=False),
            sa.Column("provenance", sa.String(32), nullable=False),
            sa.Column("is_verified", sa.Boolean(), nullable=False),
            sa.Column("verified_by_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("verified_at", sa.DateTime()),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("x >= 0 AND x <= 1 AND y >= 0 AND y <= 1", name="ck_builder_hotspot_origin"),
            sa.CheckConstraint("width >= 0.002 AND height >= 0.002", name="ck_builder_hotspot_size"),
            sa.CheckConstraint("x + width <= 1 AND y + height <= 1", name="ck_builder_hotspot_bounds"),
            sa.CheckConstraint("version >= 1", name="ck_builder_hotspot_version"),
        )
        op.create_index("ix_catalog_revision_position_hotspots_visual_page_id",
                        "catalog_revision_position_hotspots", ["visual_page_id"])
        op.create_index("ix_catalog_revision_position_hotspots_position",
                        "catalog_revision_position_hotspots", ["position"])
    if "catalog_revision_repair_kits" not in existing:
        op.create_table(
            "catalog_revision_repair_kits",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("assembly_id", sa.Integer(), sa.ForeignKey("catalog_revision_assemblies.id"), nullable=False),
            sa.Column("code", sa.String(120), nullable=False),
            sa.Column("name_bg", sa.String(255)), sa.Column("name_en", sa.String(255)),
            sa.Column("name_ru", sa.String(255)), sa.Column("description", sa.Text()),
            sa.Column("source_visual_page_id", sa.Integer(), sa.ForeignKey("catalog_revision_visual_pages.id")),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("code_locked", sa.Boolean(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("assembly_id", "code", name="uq_builder_repair_kit_code"),
        )
        op.create_index("ix_catalog_revision_repair_kits_assembly_id", "catalog_revision_repair_kits", ["assembly_id"])
        op.create_index("ix_catalog_revision_repair_kits_source_visual_page_id",
                        "catalog_revision_repair_kits", ["source_visual_page_id"])
    if "catalog_revision_repair_kit_components" not in existing:
        op.create_table(
            "catalog_revision_repair_kit_components",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("kit_id", sa.Integer(), sa.ForeignKey("catalog_revision_repair_kits.id"), nullable=False),
            sa.Column("part_id", sa.Integer(), sa.ForeignKey("catalog_revision_parts.id"), nullable=False),
            sa.Column("quantity", sa.Numeric(14, 4), nullable=False),
            sa.Column("quantity_raw", sa.String(120)),
            sa.Column("is_optional", sa.Boolean(), nullable=False),
            sa.Column("note", sa.Text()),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("kit_id", "part_id", name="uq_builder_repair_kit_part"),
            sa.CheckConstraint("quantity > 0", name="ck_builder_repair_kit_quantity"),
        )
        op.create_index("ix_catalog_revision_repair_kit_components_kit_id",
                        "catalog_revision_repair_kit_components", ["kit_id"])
        op.create_index("ix_catalog_revision_repair_kit_components_part_id",
                        "catalog_revision_repair_kit_components", ["part_id"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("catalog_revision_repair_kit_components", "catalog_revision_repair_kits",
                  "catalog_revision_position_hotspots"):
        if bind.scalar(sa.text(f"SELECT count(*) FROM {table}")):
            raise RuntimeError("Cannot downgrade: Catalog Builder 01D staging contains data")
    op.drop_table("catalog_revision_repair_kit_components")
    op.drop_table("catalog_revision_repair_kits")
    op.drop_table("catalog_revision_position_hotspots")
