"""Add the universal industrial passport, workflow and document platform.

Revision ID: 20260731_0003
Revises: 20260731_0002
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260731_0003"
down_revision = "20260731_0002"
branch_labels = None
depends_on = None


def _explicit_upgrade() -> None:
    # Revision 0001 intentionally calls ``Base.metadata.create_all`` so that it
    # can adopt the pre-Alembic RC database. On a brand-new installation that
    # call sees the current metadata and therefore creates this revision's
    # complete schema before Alembic reaches 0003. Keep the upgrade idempotent
    # for that supported path, while still migrating databases already stamped
    # at 0002.
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())
    machine_columns = {item["name"] for item in inspector.get_columns("machines")}
    protocol_columns = {
        item["name"] for item in inspector.get_columns("protocol_documents")
    }
    if (
        "generated_documents" in table_names
        and "category_id" in machine_columns
        and "template_version_id" in protocol_columns
    ):
        return

    op.create_table(
        "asset_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name_bg", sa.String(255), nullable=False),
        sa.Column("name_en", sa.String(255)),
        sa.Column("name_ru", sa.String(255)),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_asset_categories_code", "asset_categories", ["code"])
    op.create_table(
        "category_field_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("asset_categories.id"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("label_bg", sa.String(255), nullable=False),
        sa.Column("label_en", sa.String(255)),
        sa.Column("label_ru", sa.String(255)),
        sa.Column("field_type", sa.String(30), nullable=False, server_default="TEXT"),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("options", sa.JSON()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("category_id", "code", name="uq_category_field_code"),
    )
    op.create_index(
        "ix_category_field_definitions_category_id",
        "category_field_definitions",
        ["category_id"],
    )

    op.create_table(
        "document_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("document_type", sa.String(80), nullable=False),
        sa.Column("name_bg", sa.String(255), nullable=False),
        sa.Column("name_en", sa.String(255)),
        sa.Column("name_ru", sa.String(255)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("document_type", "code", name="uq_document_template_code"),
    )
    op.create_index(
        "ix_document_templates_document_type", "document_templates", ["document_type"]
    )
    op.create_table(
        "document_template_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("document_templates.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(2), nullable=False, server_default="bg"),
        sa.Column("source_path", sa.String(700)),
        sa.Column("source_sha256", sa.String(64)),
        sa.Column("layout_contract", sa.JSON(), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("published_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime()),
        sa.UniqueConstraint(
            "template_id", "version", "language", name="uq_template_version_language"
        ),
    )
    op.create_index(
        "ix_document_template_versions_template_id",
        "document_template_versions",
        ["template_id"],
    )
    op.create_index(
        "ix_document_template_versions_created_by_id",
        "document_template_versions",
        ["created_by_id"],
    )
    op.create_index(
        "ix_document_template_versions_published_by_id",
        "document_template_versions",
        ["published_by_id"],
    )

    with op.batch_alter_table("machines") as batch:
        batch.add_column(sa.Column("category_id", sa.Integer()))
        batch.add_column(sa.Column("asset_type", sa.String(120)))
        batch.add_column(sa.Column("subtype", sa.String(120)))
        batch.add_column(sa.Column("manufacturer", sa.String(255)))
        batch.add_column(sa.Column("manufacture_year", sa.Integer()))
        batch.add_column(sa.Column("commissioning_date", sa.DateTime()))
        batch.add_column(sa.Column("ownership", sa.String(255)))
        batch.add_column(sa.Column("department", sa.String(255)))
        batch.add_column(sa.Column("responsible_person", sa.String(255)))
        batch.add_column(sa.Column("capacity", sa.String(255)))
        batch.add_column(sa.Column("dimensions", sa.String(255)))
        batch.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.create_foreign_key(
            "fk_machines_category_id_asset_categories", "asset_categories", ["category_id"], ["id"]
        )
        batch.create_index("ix_machines_category_id", ["category_id"])

    with op.batch_alter_table("repairs") as batch:
        batch.add_column(sa.Column("repair_reference", sa.String(80)))
        batch.add_column(sa.Column("repair_type", sa.String(120)))
        batch.add_column(sa.Column("severity", sa.String(80)))
        batch.add_column(sa.Column("condition_before", sa.Text()))
        batch.add_column(sa.Column("condition_after", sa.Text()))
        batch.add_column(
            sa.Column("cleaning_required", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("cleaning_completed_at", sa.DateTime()))
        batch.add_column(sa.Column("inspection_completed_at", sa.DateTime()))
        batch.add_column(
            sa.Column("test_required", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.add_column(sa.Column("test_passed", sa.Boolean()))
        batch.add_column(sa.Column("test_details", sa.Text()))
        batch.add_column(sa.Column("responsible_user_id", sa.Integer()))
        batch.add_column(sa.Column("accepted_by_id", sa.Integer()))
        batch.add_column(sa.Column("approved_by_id", sa.Integer()))
        batch.add_column(sa.Column("approved_at", sa.DateTime()))
        batch.add_column(sa.Column("target_date", sa.DateTime()))
        batch.create_unique_constraint("uq_repairs_repair_reference", ["repair_reference"])
        batch.create_foreign_key(
            "fk_repairs_responsible_user", "users", ["responsible_user_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_repairs_accepted_by", "users", ["accepted_by_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_repairs_approved_by", "users", ["approved_by_id"], ["id"]
        )
        batch.create_index("ix_repairs_repair_reference", ["repair_reference"])
        batch.create_index("ix_repairs_responsible_user_id", ["responsible_user_id"])
        batch.create_index("ix_repairs_accepted_by_id", ["accepted_by_id"])
        batch.create_index("ix_repairs_approved_by_id", ["approved_by_id"])

    with op.batch_alter_table("protocol_documents") as batch:
        batch.add_column(sa.Column("document_number", sa.String(100)))
        batch.add_column(sa.Column("language", sa.String(2), nullable=False, server_default="bg"))
        batch.add_column(sa.Column("template_version_id", sa.Integer()))
        batch.add_column(sa.Column("snapshot", sa.JSON()))
        batch.create_foreign_key(
            "fk_protocol_documents_template_version",
            "document_template_versions",
            ["template_version_id"],
            ["id"],
        )
        batch.create_index("ix_protocol_documents_document_number", ["document_number"])
        batch.create_index("ix_protocol_documents_template_version_id", ["template_version_id"])

    with op.batch_alter_table("part_requests") as batch:
        batch.add_column(sa.Column("request_reference", sa.String(80)))
        batch.add_column(sa.Column("language", sa.String(2), nullable=False, server_default="bg"))
        batch.add_column(sa.Column("requested_by_id", sa.Integer()))
        batch.add_column(sa.Column("submitted_at", sa.DateTime()))
        batch.add_column(sa.Column("decided_at", sa.DateTime()))
        batch.add_column(sa.Column("decided_by_id", sa.Integer()))
        batch.add_column(sa.Column("decision_note", sa.Text()))
        batch.create_unique_constraint("uq_part_requests_reference", ["request_reference"])
        batch.create_foreign_key(
            "fk_part_requests_requested_by", "users", ["requested_by_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_part_requests_decided_by", "users", ["decided_by_id"], ["id"]
        )
        batch.create_index("ix_part_requests_request_reference", ["request_reference"])
        batch.create_index("ix_part_requests_requested_by_id", ["requested_by_id"])
        batch.create_index("ix_part_requests_decided_by_id", ["decided_by_id"])

    with op.batch_alter_table("part_catalog") as batch:
        batch.add_column(sa.Column("manufacturer", sa.String(255)))
        batch.add_column(sa.Column("unit", sa.String(40)))
        batch.add_column(sa.Column("technical_specification", sa.Text()))
        batch.add_column(sa.Column("compatible_models", sa.Text()))
        batch.add_column(sa.Column("alternative_part_number", sa.String(120)))
        batch.add_column(sa.Column("source_excerpt", sa.Text()))
        batch.add_column(sa.Column("provenance_confidence", sa.Float()))
        batch.add_column(
            sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("verified_by_id", sa.Integer()))
        batch.add_column(sa.Column("verified_at", sa.DateTime()))
        batch.create_foreign_key(
            "fk_part_catalog_verified_by", "users", ["verified_by_id"], ["id"]
        )
        batch.create_index("ix_part_catalog_verified_by_id", ["verified_by_id"])

    with op.batch_alter_table("technical_documents") as batch:
        batch.add_column(
            sa.Column(
                "document_type", sa.String(80), nullable=False, server_default="TECHNICAL"
            )
        )
        batch.add_column(sa.Column("model", sa.String(120)))
        batch.add_column(sa.Column("language", sa.String(2)))
        batch.add_column(sa.Column("revision", sa.String(80)))
        batch.add_column(sa.Column("source_date", sa.DateTime()))
        batch.add_column(sa.Column("sha256", sa.String(64)))
        batch.add_column(sa.Column("uploaded_content", sa.LargeBinary()))
        batch.add_column(sa.Column("uploaded_filename", sa.String(255)))
        batch.add_column(sa.Column("media_type", sa.String(150)))
        batch.add_column(sa.Column("uploaded_by_id", sa.Integer()))
        batch.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key(
            "fk_technical_documents_uploaded_by", "users", ["uploaded_by_id"], ["id"]
        )
        batch.create_index("ix_technical_documents_uploaded_by_id", ["uploaded_by_id"])

    op.create_table(
        "machine_field_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_id", sa.Integer(), sa.ForeignKey("machines.id"), nullable=False),
        sa.Column(
            "field_id", sa.Integer(), sa.ForeignKey("category_field_definitions.id"), nullable=False
        ),
        sa.Column("value", sa.Text()),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("machine_id", "field_id", name="uq_machine_field_value"),
    )
    op.create_index("ix_machine_field_values_machine_id", "machine_field_values", ["machine_id"])
    op.create_index("ix_machine_field_values_field_id", "machine_field_values", ["field_id"])
    op.create_index(
        "ix_machine_field_values_updated_by_id", "machine_field_values", ["updated_by_id"]
    )
    op.create_table(
        "machine_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_id", sa.Integer(), sa.ForeignKey("machines.id"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(150), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("machine_id", "sha256", "created_by_id"):
        op.create_index(f"ix_machine_attachments_{column}", "machine_attachments", [column])
    op.create_table(
        "machine_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_id", sa.Integer(), sa.ForeignKey("machines.id"), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("reference", sa.String(100)),
        sa.Column("previous_status", sa.String(80)),
        sa.Column("new_status", sa.String(80)),
        sa.Column("previous_location_id", sa.Integer(), sa.ForeignKey("locations.id")),
        sa.Column("new_location_id", sa.Integer(), sa.ForeignKey("locations.id")),
        sa.Column("details", sa.JSON()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("machine_id", "event_type", "reference", "user_id", "created_at"):
        op.create_index(f"ix_machine_events_{column}", "machine_events", [column])
    op.create_table(
        "repair_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repair_id", sa.Integer(), sa.ForeignKey("repairs.id"), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("status_before", sa.String(80)),
        sa.Column("status_after", sa.String(80)),
        sa.Column("description", sa.Text()),
        sa.Column("structured_data", sa.JSON()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("repair_id", "event_type", "user_id", "created_at"):
        op.create_index(f"ix_repair_events_{column}", "repair_events", [column])
    op.create_table(
        "repair_parts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repair_id", sa.Integer(), sa.ForeignKey("repairs.id"), nullable=False),
        sa.Column("catalog_part_id", sa.Integer(), sa.ForeignKey("part_catalog.id")),
        sa.Column("part_number", sa.String(120)),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(40)),
        sa.Column("source", sa.String(255)),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("repair_id", "catalog_part_id", "created_by_id"):
        op.create_index(f"ix_repair_parts_{column}", "repair_parts", [column])
    op.create_table(
        "repair_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repair_id", sa.Integer(), sa.ForeignKey("repairs.id"), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(150), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("caption", sa.Text()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("repair_id", "sha256", "created_by_id"):
        op.create_index(f"ix_repair_attachments_{column}", "repair_attachments", [column])
    op.create_table(
        "part_request_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("part_requests.id"), nullable=False),
        sa.Column("catalog_part_id", sa.Integer(), sa.ForeignKey("part_catalog.id")),
        sa.Column("position", sa.String(40)),
        sa.Column("part_number", sa.String(120)),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(40)),
        sa.Column("reason", sa.Text()),
        sa.Column("source_document", sa.String(700)),
        sa.Column("source_page", sa.Integer()),
        sa.Column("delivered_quantity", sa.Float(), nullable=False, server_default="0"),
    )
    op.create_index("ix_part_request_lines_request_id", "part_request_lines", ["request_id"])
    op.create_index(
        "ix_part_request_lines_catalog_part_id", "part_request_lines", ["catalog_part_id"]
    )
    op.create_table(
        "part_request_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("part_requests.id"), nullable=False),
        sa.Column("decision", sa.String(40), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("decided_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_part_request_approvals_request_id", "part_request_approvals", ["request_id"]
    )
    op.create_index(
        "ix_part_request_approvals_decided_by_id",
        "part_request_approvals",
        ["decided_by_id"],
    )
    op.create_table(
        "part_hotspots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("part_catalog.id"), nullable=False),
        sa.Column(
            "technical_document_id", sa.Integer(), sa.ForeignKey("technical_documents.id")
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("width", sa.Float(), nullable=False),
        sa.Column("height", sa.Float(), nullable=False),
        sa.Column("label", sa.String(120)),
            sa.Column("provenance", sa.Text()),
            sa.Column("confidence", sa.Float()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("part_id", "technical_document_id", "created_by_id"):
        op.create_index(f"ix_part_hotspots_{column}", "part_hotspots", [column])
    op.create_table(
        "repair_kits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("brand", sa.String(120)),
        sa.Column("model", sa.String(120)),
        sa.Column("compatible_models", sa.Text()),
        sa.Column("revision", sa.String(80)),
        sa.Column("assembly", sa.String(255)),
        sa.Column("source_document", sa.String(700)),
        sa.Column("source_page", sa.Integer()),
        sa.Column("provenance", sa.Text()),
        sa.Column("confidence", sa.Float()),
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_repair_kits_code", "repair_kits", ["code"])
    op.create_index("ix_repair_kits_approved_by_id", "repair_kits", ["approved_by_id"])
    op.create_index("ix_repair_kits_created_by_id", "repair_kits", ["created_by_id"])
    op.create_table(
        "repair_kit_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kit_id", sa.Integer(), sa.ForeignKey("repair_kits.id"), nullable=False),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("part_catalog.id"), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.UniqueConstraint("kit_id", "part_id", name="uq_repair_kit_part"),
    )
    op.create_index("ix_repair_kit_components_kit_id", "repair_kit_components", ["kit_id"])
    op.create_index("ix_repair_kit_components_part_id", "repair_kit_components", ["part_id"])
    op.create_table(
        "technical_document_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id", sa.Integer(), sa.ForeignKey("technical_documents.id"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revision_label", sa.String(80)),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(150), nullable=False),
        sa.Column("content", sa.LargeBinary()),
        sa.Column("file_path", sa.String(700)),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("change_note", sa.Text()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("document_id", "version", name="uq_technical_document_version"),
    )
    op.create_index(
        "ix_technical_document_revisions_document_id",
        "technical_document_revisions",
        ["document_id"],
    )
    op.create_index(
        "ix_technical_document_revisions_created_by_id",
        "technical_document_revisions",
        ["created_by_id"],
    )
    op.create_table(
        "generated_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_number", sa.String(100), nullable=False),
        sa.Column("document_type", sa.String(80), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("language", sa.String(2), nullable=False, server_default="bg"),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(150), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "template_version_id", sa.Integer(), sa.ForeignKey("document_template_versions.id")
        ),
        sa.Column("machine_id", sa.Integer(), sa.ForeignKey("machines.id")),
        sa.Column("repair_id", sa.Integer(), sa.ForeignKey("repairs.id")),
        sa.Column("part_request_id", sa.Integer(), sa.ForeignKey("part_requests.id")),
        sa.Column("transfer_id", sa.Integer(), sa.ForeignKey("transfer_protocols.id")),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("transfer_batches.id")),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("document_number", "format", name="uq_generated_number_format"),
    )
    for column in (
        "document_number",
        "document_type",
        "template_version_id",
        "machine_id",
        "repair_id",
        "part_request_id",
        "transfer_id",
        "batch_id",
        "created_by_id",
    ):
        op.create_index(f"ix_generated_documents_{column}", "generated_documents", [column])


def _ensure_columns(table_name: str, columns: list[sa.Column]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    missing = [column for column in columns if column.name not in existing]
    if not missing:
        return
    with op.batch_alter_table(table_name) as batch:
        for column in missing:
            batch.add_column(column)


def _ensure_index(table_name: str, name: str, columns: list[str]) -> None:
    existing = {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    }
    if name not in existing:
        op.create_index(name, table_name, columns)


def _ensure_unique(table_name: str, name: str, columns: list[str]) -> None:
    existing = {
        constraint.get("name")
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table_name)
    }
    if name not in existing:
        with op.batch_alter_table(table_name) as batch:
            batch.create_unique_constraint(name, columns)


def upgrade() -> None:
    # Revision 0001 adopts the pre-Alembic RC through create_all. Repeating that
    # safe operation here creates only tables that are absent after a downgrade;
    # the explicit column adoption below handles legacy tables that already
    # existed and therefore were not altered by create_all.
    import app.models  # noqa: F401
    from app.database import Base

    Base.metadata.create_all(bind=op.get_bind())

    _ensure_columns(
        "document_template_versions",
        [
            sa.Column("source_filename", sa.String(255)),
            sa.Column("source_media_type", sa.String(150)),
            sa.Column("source_content", sa.LargeBinary()),
            sa.Column("effective_from", sa.DateTime()),
            sa.Column("effective_to", sa.DateTime()),
            sa.Column("required_fields", sa.JSON()),
            sa.Column("numbering_rule", sa.String(255)),
            sa.Column("department", sa.String(255)),
            sa.Column("change_note", sa.Text()),
        ],
    )

    _ensure_columns(
        "asset_categories",
        [
            sa.Column("icon", sa.String(120)),
            sa.Column("validation_rules", sa.JSON()),
            sa.Column("document_types", sa.JSON()),
            sa.Column("checklists", sa.JSON()),
            sa.Column("status_codes", sa.JSON()),
        ],
    )
    _ensure_columns(
        "category_field_definitions",
        [
            sa.Column("unit", sa.String(40)),
            sa.Column("validation_rules", sa.JSON()),
        ],
    )

    _ensure_columns(
        "locations",
        [
            sa.Column(
                "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
            )
        ],
    )

    _ensure_columns(
        "machines",
        [
            sa.Column(
                "category_id",
                sa.Integer(),
                sa.ForeignKey(
                    "asset_categories.id",
                    name="fk_machines_category_id_asset_categories",
                ),
            ),
            sa.Column("asset_type", sa.String(120)),
            sa.Column("subtype", sa.String(120)),
            sa.Column("manufacturer", sa.String(255)),
            sa.Column("manufacture_year", sa.Integer()),
            sa.Column("commissioning_date", sa.DateTime()),
            sa.Column("ownership", sa.String(255)),
            sa.Column("department", sa.String(255)),
            sa.Column("responsible_person", sa.String(255)),
            sa.Column("capacity", sa.String(255)),
            sa.Column("dimensions", sa.String(255)),
            sa.Column(
                "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
        ],
    )
    _ensure_index("machines", "ix_machines_category_id", ["category_id"])

    _ensure_columns(
        "repairs",
        [
            sa.Column("repair_reference", sa.String(80)),
            sa.Column("repair_type", sa.String(120)),
            sa.Column("severity", sa.String(80)),
            sa.Column("condition_before", sa.Text()),
            sa.Column("condition_after", sa.Text()),
            sa.Column("reported_by_name", sa.String(255)),
            sa.Column("symptoms", sa.Text()),
            sa.Column("required_work", sa.Text()),
            sa.Column("removed_parts_text", sa.Text()),
            sa.Column(
                "cleaning_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("cleaning_completed_at", sa.DateTime()),
            sa.Column("inspection_completed_at", sa.DateTime()),
            sa.Column(
                "test_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column("test_passed", sa.Boolean()),
            sa.Column("test_details", sa.Text()),
            sa.Column("test_method", sa.Text()),
            sa.Column("test_pressure_bar", sa.Integer()),
            sa.Column("leaks_detected", sa.Boolean()),
            sa.Column("electrical_test_result", sa.Text()),
            sa.Column("functional_test_result", sa.Text()),
            sa.Column(
                "responsible_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", name="fk_repairs_responsible_user"),
            ),
            sa.Column(
                "accepted_by_id",
                sa.Integer(),
                sa.ForeignKey("users.id", name="fk_repairs_accepted_by"),
            ),
            sa.Column(
                "approved_by_id",
                sa.Integer(),
                sa.ForeignKey("users.id", name="fk_repairs_approved_by"),
            ),
            sa.Column("approved_at", sa.DateTime()),
            sa.Column("target_date", sa.DateTime()),
            sa.Column("started_at", sa.DateTime()),
        ],
    )
    _ensure_unique("repairs", "uq_repairs_repair_reference", ["repair_reference"])
    _ensure_index("repairs", "ix_repairs_repair_reference", ["repair_reference"])
    _ensure_index("repairs", "ix_repairs_responsible_user_id", ["responsible_user_id"])
    _ensure_index("repairs", "ix_repairs_accepted_by_id", ["accepted_by_id"])
    _ensure_index("repairs", "ix_repairs_approved_by_id", ["approved_by_id"])

    _ensure_columns(
        "transfer_protocols",
        [
            sa.Column("department", sa.String(255)),
            sa.Column("dock", sa.String(120)),
            sa.Column("pier", sa.String(120)),
            sa.Column("work_area", sa.String(255)),
            sa.Column("hoses", sa.Text()),
            sa.Column("nozzles", sa.Text()),
            sa.Column("guns", sa.Text()),
            sa.Column("accessories", sa.Text()),
            sa.Column("return_missing_equipment", sa.Text()),
            sa.Column("return_damage", sa.Text()),
            sa.Column("return_contamination", sa.Text()),
            sa.Column(
                "return_cleaning_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "return_inspection_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "return_repair_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        ],
    )

    _ensure_columns(
        "protocol_documents",
        [
            sa.Column("document_number", sa.String(100)),
            sa.Column("language", sa.String(2), nullable=False, server_default="bg"),
            sa.Column(
                "template_version_id",
                sa.Integer(),
                sa.ForeignKey(
                    "document_template_versions.id",
                    name="fk_protocol_documents_template_version",
                ),
            ),
            sa.Column("snapshot", sa.JSON()),
        ],
    )
    _ensure_index(
        "protocol_documents",
        "ix_protocol_documents_document_number",
        ["document_number"],
    )
    _ensure_index(
        "protocol_documents",
        "ix_protocol_documents_template_version_id",
        ["template_version_id"],
    )

    _ensure_columns(
        "part_requests",
        [
            sa.Column("request_reference", sa.String(80)),
            sa.Column(
                "repair_id",
                sa.Integer(),
                sa.ForeignKey("repairs.id", name="fk_part_requests_repair"),
            ),
            sa.Column("language", sa.String(2), nullable=False, server_default="bg"),
            sa.Column(
                "requested_by_id",
                sa.Integer(),
                sa.ForeignKey("users.id", name="fk_part_requests_requested_by"),
            ),
            sa.Column("submitted_at", sa.DateTime()),
            sa.Column("decided_at", sa.DateTime()),
            sa.Column(
                "decided_by_id",
                sa.Integer(),
                sa.ForeignKey("users.id", name="fk_part_requests_decided_by"),
            ),
            sa.Column("decision_note", sa.Text()),
            sa.Column("department", sa.String(255)),
            sa.Column("supplier", sa.String(255)),
            sa.Column("delivery_note", sa.Text()),
            sa.Column("ordered_at", sa.DateTime()),
            sa.Column("delivered_at", sa.DateTime()),
            sa.Column(
                "repair_kit_id",
                sa.Integer(),
                sa.ForeignKey("repair_kits.id", name="fk_part_requests_repair_kit"),
            ),
            sa.Column("repair_kit_mode", sa.String(20)),
        ],
    )
    _ensure_unique(
        "part_requests", "uq_part_requests_reference", ["request_reference"]
    )
    _ensure_index(
        "part_requests", "ix_part_requests_request_reference", ["request_reference"]
    )
    _ensure_index("part_requests", "ix_part_requests_repair_id", ["repair_id"])
    _ensure_index(
        "part_requests", "ix_part_requests_requested_by_id", ["requested_by_id"]
    )
    _ensure_index(
        "part_requests", "ix_part_requests_decided_by_id", ["decided_by_id"]
    )
    _ensure_index(
        "part_requests", "ix_part_requests_repair_kit_id", ["repair_kit_id"]
    )

    _ensure_columns(
        "repair_kit_components",
        [
            sa.Column(
                "is_optional", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        ],
    )

    _ensure_columns(
        "repair_kits",
        [
            sa.Column("compatible_models", sa.Text()),
            sa.Column("revision", sa.String(80)),
        ],
    )

    _ensure_columns(
        "part_hotspots",
        [sa.Column("confidence", sa.Float())],
    )

    _ensure_columns(
        "part_catalog",
        [
            sa.Column("manufacturer", sa.String(255)),
            sa.Column("category", sa.String(120)),
            sa.Column("name_bg", sa.String(255)),
            sa.Column("name_en", sa.String(255)),
            sa.Column("name_ru", sa.String(255)),
            sa.Column("original_name", sa.String(500)),
            sa.Column("unit", sa.String(40)),
            sa.Column("technical_specification", sa.Text()),
            sa.Column("compatible_models", sa.Text()),
            sa.Column("compatible_machine_numbers", sa.JSON()),
            sa.Column("technical_notes", sa.Text()),
            sa.Column("supplier", sa.String(255)),
            sa.Column("supplier_code", sa.String(120)),
            sa.Column("estimated_price", sa.Float()),
            sa.Column("currency", sa.String(3)),
            sa.Column("lead_time_days", sa.Integer()),
            sa.Column("revision", sa.String(80)),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("alternative_part_number", sa.String(120)),
            sa.Column("alternative_part_numbers", sa.JSON()),
            sa.Column("replacement_part_ids", sa.JSON()),
            sa.Column("source_excerpt", sa.Text()),
            sa.Column("provenance_confidence", sa.Float()),
            sa.Column(
                "is_verified", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column(
                "verified_by_id",
                sa.Integer(),
                sa.ForeignKey("users.id", name="fk_part_catalog_verified_by"),
            ),
            sa.Column("verified_at", sa.DateTime()),
        ],
    )
    _ensure_index(
        "part_catalog", "ix_part_catalog_verified_by_id", ["verified_by_id"]
    )
    _ensure_unique(
        "part_catalog",
        "uq_part_catalog_source_position",
        ["brand", "model", "assembly", "position", "part_number"],
    )

    _ensure_columns(
        "technical_documents",
        [
            sa.Column(
                "document_type",
                sa.String(80),
                nullable=False,
                server_default="TECHNICAL",
            ),
            sa.Column("model", sa.String(120)),
            sa.Column("language", sa.String(2)),
            sa.Column("revision", sa.String(80)),
            sa.Column("source_date", sa.DateTime()),
            sa.Column("source_label", sa.String(500)),
            sa.Column("document_date", sa.DateTime()),
            sa.Column("tags", sa.JSON()),
            sa.Column("extracted_text", sa.Text()),
            sa.Column("page_count", sa.Integer()),
            sa.Column("notes", sa.Text()),
            sa.Column("linked_machine_numbers", sa.JSON()),
            sa.Column("sha256", sa.String(64)),
            sa.Column("uploaded_content", sa.LargeBinary()),
            sa.Column("uploaded_filename", sa.String(255)),
            sa.Column("media_type", sa.String(150)),
            sa.Column(
                "uploaded_by_id",
                sa.Integer(),
                sa.ForeignKey(
                    "users.id", name="fk_technical_documents_uploaded_by"
                ),
            ),
            sa.Column("created_at", sa.DateTime()),
        ],
    )
    _ensure_index(
        "technical_documents",
        "ix_technical_documents_uploaded_by_id",
        ["uploaded_by_id"],
    )


def downgrade() -> None:
    op.drop_table("generated_documents")
    op.drop_table("part_request_attachments")
    op.drop_table("part_catalog_images")
    op.drop_table("departments")
    op.drop_table("technical_document_revisions")
    op.drop_table("repair_kit_components")
    with op.batch_alter_table("part_requests") as batch:
        batch.drop_index("ix_part_requests_repair_kit_id")
        batch.drop_column("repair_kit_id")
        batch.drop_column("repair_kit_mode")
    op.drop_table("repair_kits")
    op.drop_table("part_hotspots")
    op.drop_table("part_request_approvals")
    op.drop_table("part_request_lines")
    op.drop_table("repair_attachments")
    op.drop_table("repair_parts")
    op.drop_table("repair_events")
    op.drop_table("machine_events")
    op.drop_table("machine_attachments")
    op.drop_table("machine_field_values")

    with op.batch_alter_table("transfer_protocols") as batch:
        for column in (
            "return_repair_required", "return_inspection_required",
            "return_cleaning_required", "return_contamination", "return_damage",
            "return_missing_equipment", "accessories", "guns", "nozzles", "hoses",
            "work_area", "pier", "dock", "department",
        ):
            batch.drop_column(column)

    with op.batch_alter_table("technical_documents") as batch:
        batch.drop_index("ix_technical_documents_uploaded_by_id")
        for column in (
            "created_at", "uploaded_by_id", "media_type", "uploaded_filename",
            "uploaded_content", "sha256", "source_date", "revision", "language",
            "model", "document_type", "source_label", "document_date", "tags",
            "extracted_text", "page_count", "notes", "linked_machine_numbers",
        ):
            batch.drop_column(column)
    part_catalog_constraints = {
        item.get("name")
        for item in sa.inspect(op.get_bind()).get_unique_constraints("part_catalog")
    }
    with op.batch_alter_table("part_catalog") as batch:
        batch.drop_index("ix_part_catalog_verified_by_id")
        if "uq_part_catalog_source_position" in part_catalog_constraints:
            batch.drop_constraint("uq_part_catalog_source_position", type_="unique")
        for column in (
            "verified_at", "verified_by_id", "is_verified", "provenance_confidence",
            "source_excerpt", "alternative_part_number", "alternative_part_numbers",
            "replacement_part_ids", "compatible_models",
            "technical_specification", "unit", "manufacturer", "category",
            "name_bg", "name_en", "name_ru", "original_name",
            "compatible_machine_numbers", "technical_notes", "supplier",
            "supplier_code", "estimated_price", "currency", "lead_time_days",
            "revision", "is_active",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("part_requests") as batch:
        batch.drop_index("ix_part_requests_decided_by_id")
        batch.drop_index("ix_part_requests_repair_id")
        batch.drop_index("ix_part_requests_requested_by_id")
        batch.drop_index("ix_part_requests_request_reference")
        for column in (
            "decision_note", "department", "supplier", "delivery_note",
            "ordered_at", "delivered_at", "decided_by_id", "decided_at", "submitted_at",
            "requested_by_id", "language", "repair_id", "request_reference",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("protocol_documents") as batch:
        batch.drop_index("ix_protocol_documents_template_version_id")
        batch.drop_index("ix_protocol_documents_document_number")
        for column in ("snapshot", "template_version_id", "language", "document_number"):
            batch.drop_column(column)
    with op.batch_alter_table("repairs") as batch:
        batch.drop_index("ix_repairs_approved_by_id")
        batch.drop_index("ix_repairs_accepted_by_id")
        batch.drop_index("ix_repairs_responsible_user_id")
        batch.drop_index("ix_repairs_repair_reference")
        for column in (
            "target_date", "started_at", "approved_at", "approved_by_id", "accepted_by_id",
            "responsible_user_id", "test_details", "test_passed", "test_required",
            "inspection_completed_at", "cleaning_completed_at", "cleaning_required",
            "condition_after", "condition_before", "severity", "repair_type",
            "repair_reference", "reported_by_name", "symptoms", "required_work",
            "removed_parts_text", "test_method", "test_pressure_bar", "leaks_detected",
            "electrical_test_result", "functional_test_result",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("machines") as batch:
        batch.drop_index("ix_machines_category_id")
        for column in (
            "is_active", "dimensions", "capacity", "responsible_person", "department",
            "ownership", "commissioning_date", "manufacture_year", "manufacturer",
            "subtype", "asset_type", "category_id",
        ):
            batch.drop_column(column)

    with op.batch_alter_table("locations") as batch:
        batch.drop_column("is_active")

    op.drop_table("document_template_versions")
    op.drop_table("document_templates")
    op.drop_table("category_field_definitions")
    op.drop_table("asset_categories")
