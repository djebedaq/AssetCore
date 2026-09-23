"""Explicit live catalog visual roles; historical snapshots remain untouched."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260923_0023"
down_revision = "20260920_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The initial bootstrap revision creates current metadata on fresh installs.
    if "catalog_visual_sources" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "catalog_visual_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("catalog_revision", sa.String(length=255), nullable=False),
        sa.Column("technical_document_id", sa.Integer(), sa.ForeignKey("technical_documents.id"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("source_id", "catalog_revision", "technical_document_id", "page_number", "role", name="uq_catalog_visual_source_revision_page_role"),
        sa.CheckConstraint("length(catalog_revision) > 0", name="ck_catalog_visual_source_revision"),
        sa.CheckConstraint("page_number > 0", name="ck_catalog_visual_source_page"),
        sa.CheckConstraint("role IN ('EXPLODED_SCHEME', 'SPARE_PARTS_LIST')", name="ck_catalog_visual_source_role"),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_catalog_visual_source_hash"),
    )
    op.create_index("ix_catalog_visual_sources_source_id", "catalog_visual_sources", ["source_id"])
    op.create_index("ix_catalog_visual_sources_technical_document_id", "catalog_visual_sources", ["technical_document_id"])
    op.create_table(
        "catalog_visual_part_maps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("visual_source_id", sa.Integer(), sa.ForeignKey("catalog_visual_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("part_catalog.id"), nullable=False),
        sa.UniqueConstraint("visual_source_id", "part_id", name="uq_catalog_visual_part_map"),
    )
    op.create_index("ix_catalog_visual_part_maps_visual_source_id", "catalog_visual_part_maps", ["visual_source_id"])
    op.create_index("ix_catalog_visual_part_maps_part_id", "catalog_visual_part_maps", ["part_id"])


def downgrade() -> None:
    op.drop_table("catalog_visual_part_maps")
    op.drop_table("catalog_visual_sources")
