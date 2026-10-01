"""Shared source bytes and reviewable, checkpointed catalog ingestion.

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
    create_table("catalog_ingest_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("catalog_revisions.id"), nullable=False),
        sa.Column("source_blob_id", sa.Integer(), sa.ForeignKey("catalog_source_blobs.id"), nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("extractor_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("next_page", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("claim_token", sa.String(36)),
        sa.Column("claim_expires_at", sa.DateTime()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("revision_id", "sha256", "extractor_version", name="uq_catalog_ingest_identity"),
        sa.CheckConstraint("status IN ('RUNNING', 'COMPLETED', 'FAILED', 'DISMISSED')", name="ck_catalog_ingest_status"),
        sa.CheckConstraint("next_page >= 1", name="ck_catalog_ingest_next_page"))
    create_index("ix_catalog_ingest_runs_revision_id", "catalog_ingest_runs", ["revision_id"])
    create_table("catalog_ingest_pages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("catalog_ingest_runs.id"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.UniqueConstraint("run_id", "page_number", name="uq_catalog_ingest_page"))
    create_index("ix_catalog_ingest_pages_run_id", "catalog_ingest_pages", ["run_id"])
    create_table("catalog_ingest_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("catalog_ingest_runs.id"), nullable=False),
        sa.Column("source_key", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("page_number", sa.Integer()),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer()),
        sa.Column("reviewed_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", "source_key", name="uq_catalog_ingest_candidate"),
        sa.CheckConstraint("kind IN ('GROUP', 'PAGE', 'PART', 'HOTSPOT')", name="ck_catalog_candidate_kind"),
        sa.CheckConstraint("state IN ('PROPOSED', 'NEEDS_REVIEW', 'ACCEPTED', 'REJECTED')", name="ck_catalog_candidate_state"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_catalog_candidate_confidence"),
        sa.CheckConstraint("version >= 1", name="ck_catalog_candidate_version"))
    create_index("ix_catalog_ingest_candidates_run_id", "catalog_ingest_candidates", ["run_id"])
    create_index("ix_catalog_candidate_review", "catalog_ingest_candidates", ["run_id", "kind", "state", "id"])


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM catalog_source_blobs")):
        raise RuntimeError("Cannot downgrade with shared source evidence; export before downgrading")
    op.drop_table("catalog_ingest_candidates")
    op.drop_table("catalog_ingest_pages")
    op.drop_table("catalog_ingest_runs")
    for table in ("technical_document_revisions", "technical_documents", "catalog_revision_artifacts"):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_source_blob_id")
            batch.drop_constraint(f"fk_{table}_source_blob", type_="foreignkey")
            batch.drop_column("source_blob_id")
    op.drop_table("catalog_source_blobs")
