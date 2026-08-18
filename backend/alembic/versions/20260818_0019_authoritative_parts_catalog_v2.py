"""authoritative position-centric parts catalog v2

Revision ID: 20260818_0019
Revises: 20260810_0018
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_0019"
down_revision = "20260810_0018"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table)
        if index.get("name")
    }


def _unique_constraints(table: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table)
        if constraint.get("name")
    }


def _add_columns(table: str, definitions: list[sa.Column]) -> None:
    existing = _columns(table)
    missing = [column for column in definitions if column.name not in existing]
    if missing:
        with op.batch_alter_table(table) as batch:
            for column in missing:
                batch.add_column(column)


def _create_index_if_missing(
    table: str, name: str, columns: list[str], *, unique: bool = False
) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def _drop_index_if_present(table: str, name: str) -> None:
    if name in _indexes(table):
        op.drop_index(name, table_name=table)


def upgrade() -> None:
    if "uq_part_catalog_source_position" in _unique_constraints("part_catalog"):
        with op.batch_alter_table("part_catalog") as batch:
            batch.drop_constraint("uq_part_catalog_source_position", type_="unique")

    _add_columns(
        "part_catalog",
        [
            sa.Column("source_record_key", sa.String(500), nullable=True),
            sa.Column("source_id", sa.String(120), nullable=True),
            sa.Column("source_row_index", sa.Integer(), nullable=True),
            sa.Column("family", sa.String(80), nullable=True),
            sa.Column("quantity_raw", sa.String(120), nullable=True),
            sa.Column("description_de", sa.Text(), nullable=True),
            sa.Column("description_en", sa.Text(), nullable=True),
            sa.Column("description_fr", sa.Text(), nullable=True),
            sa.Column("description_2", sa.Text(), nullable=True),
            sa.Column("valid_for_raw", sa.Text(), nullable=True),
            sa.Column("repair_kit_code", sa.String(120), nullable=True),
            sa.Column("source_anomaly_codes", sa.JSON(), nullable=True),
        ],
    )
    _create_index_if_missing(
        "part_catalog",
        "ix_part_catalog_source_record_key",
        ["source_record_key"],
        unique=True,
    )
    _create_index_if_missing("part_catalog", "ix_part_catalog_source_id", ["source_id"])
    _create_index_if_missing("part_catalog", "ix_part_catalog_family", ["family"])
    _create_index_if_missing(
        "part_catalog", "ix_part_catalog_repair_kit_code", ["repair_kit_code"]
    )

    _add_columns(
        "technical_documents",
        [
            sa.Column("source_id", sa.String(120), nullable=True),
            sa.Column("dataset_version", sa.String(80), nullable=True),
            sa.Column("allowed_pages", sa.JSON(), nullable=True),
            sa.Column(
                "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
        ],
    )
    _create_index_if_missing(
        "technical_documents", "ix_technical_documents_source_id", ["source_id"]
    )
    _create_index_if_missing(
        "technical_documents",
        "ix_technical_documents_dataset_version",
        ["dataset_version"],
    )
    _create_index_if_missing(
        "technical_documents", "ix_technical_documents_is_active", ["is_active"]
    )

    _add_columns(
        "repair_kits",
        [
            sa.Column("family", sa.String(80), nullable=True),
            sa.Column("source_id", sa.String(120), nullable=True),
            sa.Column("source_version", sa.String(80), nullable=True),
            sa.Column("source_document_sha256", sa.String(64), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        ],
    )
    _create_index_if_missing("repair_kits", "ix_repair_kits_family", ["family"])
    _create_index_if_missing("repair_kits", "ix_repair_kits_source_id", ["source_id"])
    _create_index_if_missing(
        "repair_kits", "ix_repair_kits_source_version", ["source_version"]
    )
    _create_index_if_missing("repair_kits", "ix_repair_kits_is_active", ["is_active"])

    _add_columns(
        "repair_kit_components",
        [
            sa.Column("quantity_raw", sa.String(120), nullable=True),
            sa.Column("source_record_key", sa.String(500), nullable=True),
            sa.Column("source_document", sa.String(700), nullable=True),
            sa.Column("source_page", sa.Integer(), nullable=True),
        ],
    )

    tables = _tables()
    if "catalog_diagrams" not in tables:
        op.create_table(
            "catalog_diagrams",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source_id", sa.String(120), nullable=False),
            sa.Column("family", sa.String(80), nullable=False),
            sa.Column("assembly", sa.String(120), nullable=False),
            sa.Column(
                "technical_document_id",
                sa.Integer(),
                sa.ForeignKey("technical_documents.id"),
                nullable=False,
            ),
            sa.Column("page_number", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("source_pdf_sha256", sa.String(64), nullable=False),
            sa.Column(
                "render_version",
                sa.String(80),
                nullable=False,
                server_default="PDF_PREVIEW_V1",
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "source_id", "page_number", name="uq_catalog_diagram_source_page"
            ),
        )
        op.create_index("ix_catalog_diagrams_source_id", "catalog_diagrams", ["source_id"])
        op.create_index("ix_catalog_diagrams_family", "catalog_diagrams", ["family"])
        op.create_index("ix_catalog_diagrams_assembly", "catalog_diagrams", ["assembly"])
        op.create_index(
            "ix_catalog_diagrams_technical_document_id",
            "catalog_diagrams",
            ["technical_document_id"],
        )
        op.create_index(
            "ix_catalog_diagrams_source_pdf_sha256",
            "catalog_diagrams",
            ["source_pdf_sha256"],
        )

    if "catalog_position_hotspots" not in _tables():
        op.create_table(
            "catalog_position_hotspots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("hotspot_key", sa.String(500), nullable=False),
            sa.Column(
                "diagram_id",
                sa.Integer(),
                sa.ForeignKey("catalog_diagrams.id"),
                nullable=False,
            ),
            sa.Column("position", sa.String(40), nullable=False),
            sa.Column("x", sa.Float(), nullable=False),
            sa.Column("y", sa.Float(), nullable=False),
            sa.Column("width", sa.Float(), nullable=False),
            sa.Column("height", sa.Float(), nullable=False),
            sa.Column("provenance", sa.Text(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column(
                "is_verified", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column("verified_by_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("hotspot_key"),
        )
        for name, columns in (
            ("ix_catalog_position_hotspots_hotspot_key", ["hotspot_key"]),
            ("ix_catalog_position_hotspots_diagram_id", ["diagram_id"]),
            ("ix_catalog_position_hotspots_position", ["position"]),
            ("ix_catalog_position_hotspots_is_verified", ["is_verified"]),
            ("ix_catalog_position_hotspots_verified_by_id", ["verified_by_id"]),
            ("ix_catalog_position_hotspots_created_by_id", ["created_by_id"]),
        ):
            op.create_index(name, "catalog_position_hotspots", columns)


def downgrade() -> None:
    tables = _tables()
    if "catalog_position_hotspots" in tables:
        op.drop_table("catalog_position_hotspots")
    if "catalog_diagrams" in tables:
        op.drop_table("catalog_diagrams")

    for table, names in {
        "part_catalog": [
            "ix_part_catalog_source_record_key",
            "ix_part_catalog_source_id",
            "ix_part_catalog_family",
            "ix_part_catalog_repair_kit_code",
        ],
        "technical_documents": [
            "ix_technical_documents_source_id",
            "ix_technical_documents_dataset_version",
            "ix_technical_documents_is_active",
        ],
        "repair_kits": [
            "ix_repair_kits_family",
            "ix_repair_kits_source_id",
            "ix_repair_kits_source_version",
            "ix_repair_kits_is_active",
        ],
    }.items():
        for name in names:
            _drop_index_if_present(table, name)

    removals = {
        "repair_kit_components": [
            "source_page",
            "source_document",
            "source_record_key",
            "quantity_raw",
        ],
        "repair_kits": [
            "is_active",
            "source_document_sha256",
            "source_version",
            "source_id",
            "family",
        ],
        "technical_documents": [
            "is_active",
            "allowed_pages",
            "dataset_version",
            "source_id",
        ],
        "part_catalog": [
            "source_anomaly_codes",
            "repair_kit_code",
            "valid_for_raw",
            "description_2",
            "description_fr",
            "description_en",
            "description_de",
            "quantity_raw",
            "family",
            "source_row_index",
            "source_id",
            "source_record_key",
        ],
    }
    for table, requested in removals.items():
        present = [column for column in requested if column in _columns(table)]
        if present:
            with op.batch_alter_table(table) as batch:
                for column in present:
                    batch.drop_column(column)

    # The v2 source intentionally contains rows that share the legacy identity.
    # Restoring the old constraint would require deleting source-backed rows, so
    # downgrade leaves it absent rather than corrupting catalog history.
