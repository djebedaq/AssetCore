"""Shared source bytes and human-defined logical reference pages.

Revision ID: 20261001_0031
Revises: 20260930_0030
"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_0031"
down_revision = "20260930_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing byte columns and all historical rows remain untouched.
    # 0001/0003 deliberately bootstrap current metadata on fresh installations.
    # Adopt that schema as well as genuinely upgrading an existing 0030 database.
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())

    def create_table(name, *columns):
        if name not in existing:
            op.create_table(name, *columns)

    def create_index(name, table, columns):
        if table not in existing or name not in {item['name'] for item in inspector.get_indexes(table)}:
            op.create_index(name, table, columns)

    create_table("catalog_source_blobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("byte_length > 0", name="ck_catalog_blob_length"))
    for table in ("catalog_revision_artifacts", "technical_documents", "technical_document_revisions"):
        if "source_blob_id" in {item["name"] for item in inspector.get_columns(table)}:
            continue
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("source_blob_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(f"fk_{table}_source_blob", "catalog_source_blobs", ["source_blob_id"], ["id"])
            batch.create_index(f"ix_{table}_source_blob_id", ["source_blob_id"])
    create_table("catalog_revision_reference_pages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assembly_id", sa.Integer(), sa.ForeignKey("catalog_revision_assemblies.id"), nullable=False),
        sa.Column("stable_key", sa.String(36), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("assembly_id", "stable_key", name="uq_reference_page_identity"),
        sa.CheckConstraint("sort_order >= 0", name="ck_reference_page_order"),
        sa.CheckConstraint("version >= 1", name="ck_reference_page_version"))
    create_index("ix_catalog_revision_reference_pages_assembly_id", "catalog_revision_reference_pages", ["assembly_id"])
    for table in ("catalog_revision_visual_pages", "catalog_revision_parts"):
        columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}
        if "reference_page_id" not in columns:
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column("reference_page_id", sa.Integer(), nullable=True))
                batch.create_foreign_key(f"fk_{table}_reference_page", "catalog_revision_reference_pages", ["reference_page_id"], ["id"])
                batch.create_index(f"ix_{table}_reference_page_id", ["reference_page_id"])
                if table == "catalog_revision_parts":
                    batch.add_column(sa.Column("extraction_key", sa.String(64)))
                    batch.add_column(sa.Column("extraction_evidence", sa.JSON()))
                    batch.create_unique_constraint("uq_part_extraction_source", ["reference_page_id", "extraction_key"])
                else:
                    batch.add_column(sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
        constraints = {item["name"] for item in sa.inspect(op.get_bind()).get_unique_constraints(table)}
        old = "uq_catalog_revision_part_identity" if table.endswith("parts") else "uq_catalog_revision_visual_page_role"
        if old in constraints:
            with op.batch_alter_table(table) as batch:
                batch.drop_constraint(old, type_="unique")
        indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
        if table.endswith("parts"):
            specs = [("uq_part_legacy", ["assembly_id", "position", "part_number"], "IS NULL"),
                     ("uq_part_guided", ["reference_page_id", "position", "part_number"], "IS NOT NULL")]
        else:
            specs = [("uq_visual_page_legacy", ["artifact_id", "page_number", "role"], "IS NULL"),
                     ("uq_visual_page_guided", ["reference_page_id", "artifact_id", "page_number", "role"], "IS NOT NULL")]
        for name, fields, condition in specs:
            if name not in indexes:
                predicate = sa.text(f"reference_page_id {condition}")
                op.create_index(name, table, fields, unique=True, sqlite_where=predicate, postgresql_where=predicate)


def downgrade() -> None:
    if (op.get_bind().scalar(sa.text("SELECT count(*) FROM catalog_source_blobs"))
            or op.get_bind().scalar(sa.text("SELECT count(*) FROM catalog_revision_reference_pages"))):
        raise RuntimeError("Cannot downgrade with shared or guided source evidence")
    for table in ("catalog_revision_parts", "catalog_revision_visual_pages"):
        names = ("uq_part_legacy", "uq_part_guided") if table.endswith("parts") else ("uq_visual_page_legacy", "uq_visual_page_guided")
        for name in names:
            op.drop_index(name, table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_reference_page_id")
            fk = next(item["name"] for item in sa.inspect(op.get_bind()).get_foreign_keys(table)
                      if item["constrained_columns"] == ["reference_page_id"])
            batch.drop_constraint(fk, type_="foreignkey")
            if table.endswith("parts"):
                batch.drop_constraint("uq_part_extraction_source", type_="unique")
                batch.drop_column("extraction_key")
                batch.drop_column("extraction_evidence")
                batch.create_unique_constraint("uq_catalog_revision_part_identity", ["assembly_id", "position", "part_number"])
            else:
                batch.drop_column("sort_order")
                batch.create_unique_constraint("uq_catalog_revision_visual_page_role", ["artifact_id", "page_number", "role"])
            batch.drop_column("reference_page_id")
    op.drop_table("catalog_revision_reference_pages")
    for table in ("technical_document_revisions", "technical_documents", "catalog_revision_artifacts"):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_source_blob_id")
            batch.drop_constraint(f"fk_{table}_source_blob", type_="foreignkey")
            batch.drop_column("source_blob_id")
    op.drop_table("catalog_source_blobs")
