"""Add isolated revision assemblies, PDF artifacts and explicit page roles.

Revision ID: 20260928_0026
Revises: 20260928_0025
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0026"
down_revision = "20260928_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Revision 0001 creates current metadata on fresh installs.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "catalog_revision_assemblies" not in existing:
        op.create_table(
            "catalog_revision_assemblies",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("revision_id", sa.Integer(), sa.ForeignKey("catalog_revisions.id"), nullable=False),
            sa.Column("code", sa.String(80), nullable=False),
            sa.Column("name_bg", sa.String(255), nullable=False),
            sa.Column("name_en", sa.String(255), nullable=False),
            sa.Column("name_ru", sa.String(255), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("revision_id", "code", name="uq_catalog_revision_assembly_code"),
        )
        op.create_index("ix_catalog_revision_assemblies_revision_id", "catalog_revision_assemblies", ["revision_id"])
    if "catalog_revision_artifacts" not in existing:
        op.create_table(
            "catalog_revision_artifacts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("assembly_id", sa.Integer(), sa.ForeignKey("catalog_revision_assemblies.id"), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("filename", sa.String(255), nullable=False),
            sa.Column("media_type", sa.String(100), nullable=False),
            sa.Column("content", sa.LargeBinary(), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("page_count", sa.Integer(), nullable=False),
            sa.Column("document_reference", sa.String(255)),
            sa.Column("document_date", sa.Date()),
            sa.Column("language", sa.String(16)),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("assembly_id", "sha256", name="uq_catalog_revision_artifact_sha"),
        )
        op.create_index("ix_catalog_revision_artifacts_assembly_id", "catalog_revision_artifacts", ["assembly_id"])
    if "catalog_revision_visual_pages" not in existing:
        op.create_table(
            "catalog_revision_visual_pages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("artifact_id", sa.Integer(), sa.ForeignKey("catalog_revision_artifacts.id"), nullable=False),
            sa.Column("page_number", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(32), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("artifact_id", "page_number", "role", name="uq_catalog_revision_visual_page_role"),
            sa.CheckConstraint("page_number >= 1", name="ck_catalog_revision_visual_page_positive"),
            sa.CheckConstraint("role IN ('EXPLODED_SCHEME', 'SPARE_PARTS_LIST')", name="ck_catalog_revision_visual_page_role"),
        )
        op.create_index("ix_catalog_revision_visual_pages_artifact_id", "catalog_revision_visual_pages", ["artifact_id"])


def downgrade() -> None:
    bind = op.get_bind()
    for name in ("catalog_revision_visual_pages", "catalog_revision_artifacts", "catalog_revision_assemblies"):
        if bind.scalar(sa.text(f"SELECT count(*) FROM {name}")):
            raise RuntimeError("Cannot downgrade: Catalog Builder visual source staging contains data")
    op.drop_index("ix_catalog_revision_visual_pages_artifact_id", table_name="catalog_revision_visual_pages")
    op.drop_table("catalog_revision_visual_pages")
    op.drop_index("ix_catalog_revision_artifacts_assembly_id", table_name="catalog_revision_artifacts")
    op.drop_table("catalog_revision_artifacts")
    op.drop_index("ix_catalog_revision_assemblies_revision_id", table_name="catalog_revision_assemblies")
    op.drop_table("catalog_revision_assemblies")
