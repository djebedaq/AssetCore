"""unknown part requests and verified catalog linking

Revision ID: 20260805_0013
Revises: 20260805_0012
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260805_0013"
down_revision = "20260805_0012"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    line_columns = _columns("part_request_lines")
    additions = [
        ("is_unknown_part", sa.Column("is_unknown_part", sa.Boolean(), server_default=sa.text("false"), nullable=False)),
        ("assembly", sa.Column("assembly", sa.String(length=255), nullable=True)),
        ("note", sa.Column("note", sa.Text(), nullable=True)),
        ("linked_catalog_part_id", sa.Column("linked_catalog_part_id", sa.Integer(), nullable=True)),
        ("linked_by_id", sa.Column("linked_by_id", sa.Integer(), nullable=True)),
        ("linked_at", sa.Column("linked_at", sa.DateTime(), nullable=True)),
        ("link_note", sa.Column("link_note", sa.Text(), nullable=True)),
    ]
    missing = [(name, column) for name, column in additions if name not in line_columns]
    if missing:
        with op.batch_alter_table("part_request_lines") as batch:
            for _, column in missing:
                batch.add_column(column)
            if "linked_catalog_part_id" not in line_columns:
                batch.create_foreign_key("fk_part_request_lines_linked_catalog_part", "part_catalog", ["linked_catalog_part_id"], ["id"])
            if "linked_by_id" not in line_columns:
                batch.create_foreign_key("fk_part_request_lines_linked_by", "users", ["linked_by_id"], ["id"])
    for name, column in [
        ("ix_part_request_lines_is_unknown_part", ["is_unknown_part"]),
        ("ix_part_request_lines_linked_catalog_part_id", ["linked_catalog_part_id"]),
        ("ix_part_request_lines_linked_by_id", ["linked_by_id"]),
    ]:
        if name not in _indexes("part_request_lines"):
            op.create_index(name, "part_request_lines", column, unique=False)

    attachment_columns = _columns("part_request_attachments")
    if "request_line_id" not in attachment_columns:
        with op.batch_alter_table("part_request_attachments") as batch:
            batch.add_column(sa.Column("request_line_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_part_request_attachments_request_line", "part_request_lines", ["request_line_id"], ["id"])
    if "ix_part_request_attachments_request_line_id" not in _indexes("part_request_attachments"):
        op.create_index("ix_part_request_attachments_request_line_id", "part_request_attachments", ["request_line_id"], unique=False)


def downgrade() -> None:
    if "ix_part_request_attachments_request_line_id" in _indexes("part_request_attachments"):
        op.drop_index("ix_part_request_attachments_request_line_id", table_name="part_request_attachments")
    if "request_line_id" in _columns("part_request_attachments"):
        with op.batch_alter_table("part_request_attachments") as batch:
            batch.drop_column("request_line_id")

    for name in [
        "ix_part_request_lines_linked_by_id",
        "ix_part_request_lines_linked_catalog_part_id",
        "ix_part_request_lines_is_unknown_part",
    ]:
        if name in _indexes("part_request_lines"):
            op.drop_index(name, table_name="part_request_lines")
    removable = ["link_note", "linked_at", "linked_by_id", "linked_catalog_part_id", "note", "assembly", "is_unknown_part"]
    present = [name for name in removable if name in _columns("part_request_lines")]
    if present:
        with op.batch_alter_table("part_request_lines") as batch:
            for name in present:
                batch.drop_column(name)
