"""Durable extraction and human review. No backfill or business data updates.

Revision ID: 20261009_0033
Revises: 20261009_0032
"""
import sqlalchemy as sa
from alembic import op

revision = "20261009_0033"
down_revision = "20261009_0032"
branch_labels = None
depends_on = None


def _table(name, *columns):
    # The bootstrap uses current metadata on fresh installations.
    if name not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(name, *columns)


def upgrade():
    _table("catalog_extraction_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("catalog_revisions.id"), nullable=False),
        sa.Column("assembly_id", sa.Integer(), nullable=False),
        sa.Column("reference_page_id", sa.Integer()),
        sa.Column("scope_key", sa.String(80), nullable=False),
        sa.Column("selection_digest", sa.String(64), nullable=False),
        sa.Column("selection", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("revision_id", "scope_key", "selection_digest", name="uq_extraction_selection"))
    _table("catalog_extraction_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("catalog_extraction_sessions.id"), nullable=False),
        sa.Column("visual_page_id", sa.Integer(), nullable=False),
        sa.Column("source_blob_id", sa.Integer(), sa.ForeignKey("catalog_source_blobs.id"), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("processing_state", sa.String(24), nullable=False),
        sa.Column("review_state", sa.String(24), nullable=False),
        sa.Column("current_attempt_id", sa.Integer()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("approved_fingerprint", sa.String(64)),
        sa.Column("reviewed_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.UniqueConstraint("session_id", "visual_page_id", name="uq_extraction_source"),
        sa.CheckConstraint("processing_state IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')", name="ck_extraction_processing"),
        sa.CheckConstraint("review_state IN ('NOT_REVIEWED','NEEDS_REVIEW','VERIFIED')", name="ck_extraction_review"),
        sa.CheckConstraint("version >= 1", name="ck_extraction_version"))
    _table("catalog_extraction_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("catalog_extraction_sources.id"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("extractor", sa.String(80), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("evidence", sa.JSON()),
        sa.Column("evidence_digest", sa.String(64)),
        sa.Column("error_code", sa.String(120)),
        sa.CheckConstraint("state IN ('RUNNING','SUCCEEDED','FAILED','CANCELLED')", name="ck_extraction_attempt_state"),
        sa.CheckConstraint("kind IN ('EXTRACTION','MAPPING','CARRY_FORWARD','MANUAL')", name="ck_extraction_attempt_kind"))
    _table("catalog_extraction_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("catalog_extraction_sources.id"), nullable=False),
        sa.Column("stable_key", sa.String(64), nullable=False),
        sa.Column("original", sa.JSON(), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("part_id", sa.Integer()),
        sa.Column("part_created_at", sa.DateTime()),
        sa.Column("reason", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_id", "stable_key", name="uq_extraction_candidate"),
        sa.CheckConstraint("state IN ('PENDING','ACCEPTED','REJECTED','CONFLICT')", name="ck_extraction_candidate_state"),
        sa.CheckConstraint("version >= 1", name="ck_extraction_candidate_version"))
    _table("catalog_source_review_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("catalog_extraction_sources.id"), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("inspection_digest", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("decision = 'VERIFIED'", name="ck_source_review_decision"))
    for table, columns in {
        "catalog_extraction_sessions": ("revision_id",),
        "catalog_extraction_sources": ("session_id", "visual_page_id"),
        "catalog_extraction_attempts": ("source_id",),
        "catalog_extraction_candidates": ("source_id",),
        "catalog_source_review_decisions": ("source_id",),
    }.items():
        for column in columns:
            name = f"ix_{table}_{column}"
            if name not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}:
                op.create_index(name, table, [column])


def downgrade():
    tables = ("catalog_source_review_decisions", "catalog_extraction_candidates",
              "catalog_extraction_attempts", "catalog_extraction_sources", "catalog_extraction_sessions")
    # Downgrading an unused installation is safe; human decisions/history are not disposable.
    connection = op.get_bind()
    if any(connection.scalar(sa.select(sa.func.count()).select_from(sa.table(name))) for name in tables):
        raise RuntimeError("Durable extraction/review history cannot be discarded by downgrade")
    for name in tables:
        op.drop_table(name)
