"""Retain immutable visual evidence without inventing historical snapshots."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260920_0022"
down_revision = "20260826_0021"
branch_labels = None
depends_on = None


def guard_statements(dialect: str) -> list[str]:
    tables = ("part_visual_artifacts", "part_visual_snapshots", "part_visual_occurrences")
    statements = []
    if dialect == "postgresql":
        statements.append("""
            CREATE FUNCTION reject_part_visual_mutation() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'immutable_part_visual_history'; END;
            $$ LANGUAGE plpgsql
        """)
        for table in tables:
            statements.append(f"""CREATE TRIGGER immutable_{table}
                BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW
                EXECUTE FUNCTION reject_part_visual_mutation()""")
        statements.append("""
            CREATE FUNCTION check_part_visual_ordinal() RETURNS trigger AS $$
            BEGIN
              IF NOT EXISTS (SELECT 1 FROM part_visual_snapshots
                WHERE id = NEW.snapshot_id AND occurrence_count >= NEW.ordinal)
              THEN RAISE EXCEPTION 'invalid_part_visual_ordinal'; END IF;
              RETURN NEW;
            END; $$ LANGUAGE plpgsql
        """)
        statements.append("""CREATE TRIGGER bounded_part_visual_ordinal
            BEFORE INSERT ON part_visual_occurrences FOR EACH ROW
            EXECUTE FUNCTION check_part_visual_ordinal()""")
    else:
        for table in tables:
            for operation in ("UPDATE", "DELETE"):
                statements.append(f"""CREATE TRIGGER immutable_{table}_{operation.lower()}
                    BEFORE {operation} ON {table} BEGIN
                    SELECT RAISE(ABORT, 'immutable_part_visual_history'); END""")
        statements.append("""CREATE TRIGGER bounded_part_visual_ordinal
            BEFORE INSERT ON part_visual_occurrences WHEN NOT EXISTS
              (SELECT 1 FROM part_visual_snapshots
               WHERE id = NEW.snapshot_id AND occurrence_count >= NEW.ordinal)
            BEGIN SELECT RAISE(ABORT, 'invalid_part_visual_ordinal'); END""")
    return statements


def upgrade() -> None:
    # Published 0001 bootstraps current metadata on fresh databases.
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "part_visual_occurrences" in tables:
        return
    op.create_table(
        "part_visual_artifacts",
        sa.Column("sha256", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False),
        sa.CheckConstraint("length(sha256) = 64", name="ck_visual_artifact_hash"),
        sa.CheckConstraint(
            "byte_length > 0 AND length(content) = byte_length", name="ck_visual_artifact_length"
        ),
    )
    op.create_table(
        "part_visual_snapshots",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "line_id",
            sa.Integer(),
            sa.ForeignKey("part_request_lines.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("catalog_part_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=True),
        sa.Column("source_record_key", sa.String(length=500), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("capture_origin", sa.String(length=24), nullable=False),
        sa.Column("catalog", sa.JSON(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint("occurrence_count >= 0", name="ck_visual_snapshot_count"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_visual_snapshot_hash"),
        sa.CheckConstraint(
            "capture_origin IN ('REQUEST_CREATION', 'CATALOG_LINK')",
            name="ck_visual_snapshot_origin",
        ),
        sa.CheckConstraint("schema_version = 1", name="ck_visual_snapshot_version"),
        sa.UniqueConstraint("line_id", name="uq_part_visual_snapshot_line"),
    )
    op.create_index(
        "ix_part_visual_snapshots_catalog_part_id", "part_visual_snapshots", ["catalog_part_id"]
    )
    op.create_index("ix_part_visual_snapshots_source_id", "part_visual_snapshots", ["source_id"])
    op.create_index(
        "ix_part_visual_snapshots_source_record_key", "part_visual_snapshots", ["source_record_key"]
    )
    op.create_table(
        "part_visual_occurrences",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.Integer(),
            sa.ForeignKey("part_visual_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=24), nullable=False),
        sa.Column("hotspot_id", sa.Integer(), nullable=False),
        sa.Column("technical_document_id", sa.Integer(), nullable=False),
        sa.Column("diagram_id", sa.Integer(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("width", sa.Float(), nullable=False),
        sa.Column("height", sa.Float(), nullable=False),
        sa.Column(
            "artifact_sha256",
            sa.String(length=64),
            sa.ForeignKey("part_visual_artifacts.sha256", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "x >= 0 AND y >= 0 AND width > 0 AND height > 0 AND x + width <= 1.000001 AND y + height <= 1.000001",
            name="ck_visual_occurrence_geometry",
        ),
        sa.CheckConstraint(
            "source_kind IN ('PART_HOTSPOT', 'POSITION_HOTSPOT')", name="ck_visual_occurrence_kind"
        ),
        sa.CheckConstraint("ordinal > 0 AND page_number > 0", name="ck_visual_occurrence_page"),
        sa.UniqueConstraint("snapshot_id", "ordinal", name="uq_visual_occurrence_order"),
        sa.UniqueConstraint(
            "snapshot_id", "source_kind", "hotspot_id", name="uq_visual_occurrence_source"
        ),
    )
    op.create_index(
        "ix_part_visual_occurrences_artifact_sha256", "part_visual_occurrences", ["artifact_sha256"]
    )
    for statement in guard_statements(op.get_bind().dialect.name):
        op.execute(statement)


def downgrade() -> None:
    # Explicit downgrade removes only this feature; upgrade never rewrites history.
    op.drop_table("part_visual_occurrences")
    op.drop_table("part_visual_snapshots")
    op.drop_table("part_visual_artifacts")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS check_part_visual_ordinal()")
        op.execute("DROP FUNCTION IF EXISTS reject_part_visual_mutation()")
