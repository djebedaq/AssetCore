"""Production hardening: identity, ownership, licences and signatures.

Revision ID: 20260801_0005
Revises: 20260801_0004
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260801_0005"
down_revision = "20260801_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def create_table(name: str, *elements: object) -> None:
        if name not in sa.inspect(bind).get_table_names():
            op.create_table(name, *elements)

    def create_index(name: str, table: str, columns: list[str], unique: bool = False) -> None:
        existing = {item["name"] for item in sa.inspect(bind).get_indexes(table)}
        if name not in existing:
            op.create_index(name, table, columns, unique=unique)

    user_columns = (
        sa.Column("first_name", sa.String(120), nullable=True),
        sa.Column("middle_name", sa.String(120), nullable=True),
        sa.Column("last_name", sa.String(120), nullable=True),
        sa.Column("job_title", sa.String(255), nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("profile_status", sa.String(30), nullable=False, server_default="PROFILE_INCOMPLETE"),
        sa.Column("legal_name_exception", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("legal_name_exception_reason", sa.Text(), nullable=True),
        sa.Column("legal_name_exception_approved_by_id", sa.Integer(), nullable=True),
        sa.Column("legal_name_exception_approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
    )
    existing_user_columns = {column["name"] for column in inspector.get_columns("users")}
    missing_user_columns = [column for column in user_columns if column.name not in existing_user_columns]
    if bind.dialect.name == "sqlite":
        # Native ADD COLUMN avoids Alembic's batch-copy circular sorter for a
        # users table that also gains a self-referencing creator relationship.
        for column in missing_user_columns:
            op.add_column("users", column)
        create_index("ix_users_department_id", "users", ["department_id"])
        create_index("ix_users_created_by_id", "users", ["created_by_id"])
        create_index("ix_users_legal_name_exception_approved_by_id", "users", ["legal_name_exception_approved_by_id"])
    elif missing_user_columns:
        with op.batch_alter_table("users") as batch:
            for column in missing_user_columns:
                batch.add_column(column)
            batch.create_foreign_key("fk_users_department", "departments", ["department_id"], ["id"])
            batch.create_foreign_key("fk_users_created_by", "users", ["created_by_id"], ["id"])
            batch.create_foreign_key("fk_users_legal_name_exception_approved_by", "users", ["legal_name_exception_approved_by_id"], ["id"])
            batch.create_index("ix_users_department_id", ["department_id"])
            batch.create_index("ix_users_created_by_id", ["created_by_id"])
            batch.create_index("ix_users_legal_name_exception_approved_by_id", ["legal_name_exception_approved_by_id"])

    template_columns = (
        sa.Column("validation_status", sa.String(30), nullable=False, server_default="NOT_VALIDATED"),
        sa.Column("validation_report", sa.JSON(), nullable=True),
        sa.Column("validated_at", sa.DateTime(), nullable=True),
        sa.Column("validated_by_id", sa.Integer(), nullable=True),
    )
    existing_template_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("document_template_versions")
    }
    missing_template_columns = [
        column for column in template_columns if column.name not in existing_template_columns
    ]
    if bind.dialect.name == "sqlite":
        for column in missing_template_columns:
            op.add_column("document_template_versions", column)
        create_index("ix_document_template_versions_validated_by_id", "document_template_versions", ["validated_by_id"])
    elif missing_template_columns:
        with op.batch_alter_table("document_template_versions") as batch:
            for column in template_columns:
                batch.add_column(column)
            batch.create_foreign_key("fk_template_validated_by", "users", ["validated_by_id"], ["id"])
            batch.create_index("ix_document_template_versions_validated_by_id", ["validated_by_id"])

    create_table(
        "installation_ownership",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("designated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("designated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("transfer_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    create_index("ix_installation_ownership_owner_user_id", "installation_ownership", ["owner_user_id"], unique=True)
    owner_id = bind.execute(sa.text("SELECT id FROM users WHERE is_system_owner = true ORDER BY id LIMIT 1")).scalar()
    ownership_count = bind.execute(sa.text("SELECT COUNT(*) FROM installation_ownership")).scalar() or 0
    if owner_id is not None and ownership_count == 0:
        bind.execute(
            sa.text("INSERT INTO installation_ownership (id, owner_user_id, designated_at, version) VALUES (1, :owner_id, CURRENT_TIMESTAMP, 1)"),
            {"owner_id": owner_id},
        )

    create_table(
        "emergency_access_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("reauthenticated_at", sa.DateTime(), nullable=False),
        sa.Column("mfa_verified_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("ended_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("end_reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(80), nullable=True),
    )
    for name, columns in (
        ("ix_emergency_access_sessions_owner_user_id", ["owner_user_id"]),
        ("ix_emergency_access_sessions_started_at", ["started_at"]),
        ("ix_emergency_access_sessions_expires_at", ["expires_at"]),
        ("ix_emergency_access_sessions_ended_at", ["ended_at"]),
        ("ix_emergency_access_sessions_correlation_id", ["correlation_id"]),
    ):
        create_index(name, "emergency_access_sessions", columns)
    existing_emergency_indexes = {
        item["name"] for item in sa.inspect(bind).get_indexes("emergency_access_sessions")
    }
    if "uq_emergency_access_active_owner" not in existing_emergency_indexes:
        op.create_index(
            "uq_emergency_access_active_owner",
            "emergency_access_sessions",
            ["owner_user_id"],
            unique=True,
            postgresql_where=sa.text("ended_at IS NULL"),
            sqlite_where=sa.text("ended_at IS NULL"),
        )

    create_table(
        "software_licenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("license_id", sa.String(120), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("license_type", sa.String(40), nullable=False),
        sa.Column("client_name", sa.String(255), nullable=False),
        sa.Column("installation_id", sa.String(255), nullable=False),
        sa.Column("valid_from", sa.DateTime(), nullable=True),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("grace_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("installed_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("installed_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
    )
    for name, columns, unique in (
        ("ix_software_licenses_license_id", ["license_id"], True),
        ("ix_software_licenses_payload_sha256", ["payload_sha256"], False),
        ("ix_software_licenses_license_type", ["license_type"], False),
        ("ix_software_licenses_installation_id", ["installation_id"], False),
        ("ix_software_licenses_installed_by_id", ["installed_by_id"], False),
    ):
        create_index(name, "software_licenses", columns, unique=unique)

    create_table(
        "external_signers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("first_name", sa.String(120), nullable=False),
        sa.Column("middle_name", sa.String(120), nullable=True),
        sa.Column("last_name", sa.String(120), nullable=False),
        sa.Column("job_title", sa.String(255), nullable=False),
        sa.Column("company", sa.String(255), nullable=True),
        sa.Column("participant_role", sa.String(120), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    create_index("ix_external_signers_created_by_id", "external_signers", ["created_by_id"])

    create_table(
        "official_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_number", sa.String(100), nullable=False, unique=True),
        sa.Column("document_type", sa.String(80), nullable=False),
        sa.Column("machine_id", sa.Integer(), sa.ForeignKey("machines.id"), nullable=True),
        sa.Column("transfer_id", sa.Integer(), sa.ForeignKey("transfer_protocols.id"), nullable=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("transfer_batches.id"), nullable=True),
        sa.Column("current_version_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for name, columns, unique in (
        ("ix_official_documents_document_number", ["document_number"], True),
        ("ix_official_documents_document_type", ["document_type"], False),
        ("ix_official_documents_machine_id", ["machine_id"], False),
        ("ix_official_documents_transfer_id", ["transfer_id"], False),
        ("ix_official_documents_batch_id", ["batch_id"], False),
        ("ix_official_documents_created_by_id", ["created_by_id"], False),
    ):
        create_index(name, "official_documents", columns, unique=unique)

    create_table(
        "official_document_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("official_documents.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="DRAFT"),
        sa.Column("language", sa.String(2), nullable=False, server_default="bg"),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("docx_content", sa.LargeBinary(), nullable=True),
        sa.Column("docx_sha256", sa.String(64), nullable=True),
        sa.Column("pdf_content", sa.LargeBinary(), nullable=True),
        sa.Column("pdf_sha256", sa.String(64), nullable=True),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column("supersedes_version_id", sa.Integer(), sa.ForeignKey("official_document_versions.id"), nullable=True),
        sa.Column("prepared_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("document_id", "version", name="uq_official_document_version"),
    )
    for name, columns in (
        ("ix_official_document_versions_document_id", ["document_id"]),
        ("ix_official_document_versions_status", ["status"]),
        ("ix_official_document_versions_snapshot_sha256", ["snapshot_sha256"]),
        ("ix_official_document_versions_prepared_by_id", ["prepared_by_id"]),
    ):
        create_index(name, "official_document_versions", columns)

    create_table(
        "document_participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_version_id", sa.Integer(), sa.ForeignKey("official_document_versions.id"), nullable=False),
        sa.Column("slot_code", sa.String(80), nullable=False),
        sa.Column("participant_kind", sa.String(20), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("external_signer_id", sa.Integer(), sa.ForeignKey("external_signers.id"), nullable=True),
        sa.Column("operation_role", sa.String(120), nullable=False),
        sa.Column("identity_snapshot", sa.JSON(), nullable=False),
        sa.Column("identity_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("document_version_id", "slot_code", name="uq_document_participant_slot"),
        sa.CheckConstraint("(user_id IS NOT NULL AND external_signer_id IS NULL) OR (user_id IS NULL AND external_signer_id IS NOT NULL)", name="ck_document_participant_identity"),
    )
    for name, columns in (
        ("ix_document_participants_document_version_id", ["document_version_id"]),
        ("ix_document_participants_user_id", ["user_id"]),
        ("ix_document_participants_external_signer_id", ["external_signer_id"]),
    ):
        create_index(name, "document_participants", columns)

    create_table(
        "signature_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_type", sa.String(80), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("label_bg", sa.String(255), nullable=False),
        sa.Column("label_en", sa.String(255), nullable=True),
        sa.Column("label_ru", sa.String(255), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allowed_participant_kind", sa.String(20), nullable=False, server_default="ANY"),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("signing_mode", sa.String(20), nullable=False, server_default="PARALLEL"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("document_type", "code", name="uq_signature_slot_type_code"),
    )
    create_index("ix_signature_slots_document_type", "signature_slots", ["document_type"])

    create_table(
        "signature_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("participant_id", sa.Integer(), sa.ForeignKey("document_participants.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    create_index("ix_signature_sessions_participant_id", "signature_sessions", ["participant_id"])
    create_index("ix_signature_sessions_token_hash", "signature_sessions", ["token_hash"], unique=True)
    create_index("ix_signature_sessions_expires_at", "signature_sessions", ["expires_at"])
    create_index("ix_signature_sessions_created_by_id", "signature_sessions", ["created_by_id"])

    create_table(
        "document_signatures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("participant_id", sa.Integer(), sa.ForeignKey("document_participants.id"), nullable=False, unique=True),
        sa.Column("document_version_id", sa.Integer(), sa.ForeignKey("official_document_versions.id"), nullable=False),
        sa.Column("signature_kind", sa.String(40), nullable=False, server_default="MANUAL_GRAPHIC"),
        sa.Column("consent_text", sa.Text(), nullable=False),
        sa.Column("strokes_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("image_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("canvas_width", sa.Integer(), nullable=False),
        sa.Column("canvas_height", sa.Integer(), nullable=False),
        sa.Column("stroke_count", sa.Integer(), nullable=False),
        sa.Column("point_count", sa.Integer(), nullable=False),
        sa.Column("document_sha256", sa.String(64), nullable=False),
        sa.Column("signature_sha256", sa.String(64), nullable=False),
        sa.Column("signed_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
    )
    create_index("ix_document_signatures_participant_id", "document_signatures", ["participant_id"], unique=True)
    create_index("ix_document_signatures_document_version_id", "document_signatures", ["document_version_id"])
    create_index("ix_document_signatures_document_sha256", "document_signatures", ["document_sha256"])
    create_index("ix_document_signatures_signature_sha256", "document_signatures", ["signature_sha256"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        "document_signatures", "signature_sessions", "signature_slots",
        "document_participants", "official_document_versions", "official_documents",
        "external_signers", "software_licenses", "emergency_access_sessions",
        "installation_ownership",
    ):
        op.drop_table(table)
    template_columns = ("validated_by_id", "validated_at", "validation_report", "validation_status")
    user_columns = (
        "created_by_id", "legal_name_exception_approved_at",
        "legal_name_exception_approved_by_id", "legal_name_exception_reason", "legal_name_exception",
        "profile_status", "department_id", "job_title", "last_name",
        "middle_name", "first_name",
    )
    if bind.dialect.name == "sqlite":
        naming = {
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
        }
        template_fks = {
            tuple(item["constrained_columns"])
            for item in sa.inspect(bind).get_foreign_keys("document_template_versions")
        }
        with op.batch_alter_table(
            "document_template_versions", naming_convention=naming
        ) as batch:
            batch.drop_index("ix_document_template_versions_validated_by_id")
            if ("validated_by_id",) in template_fks:
                batch.drop_constraint(
                    "fk_document_template_versions_validated_by_id_users",
                    type_="foreignkey",
                )
            for name in template_columns:
                batch.drop_column(name)
        user_fks = {
            tuple(item["constrained_columns"])
            for item in sa.inspect(bind).get_foreign_keys("users")
        }
        with op.batch_alter_table("users", naming_convention=naming) as batch:
            batch.drop_index("ix_users_created_by_id")
            batch.drop_index("ix_users_department_id")
            batch.drop_index("ix_users_legal_name_exception_approved_by_id")
            if ("created_by_id",) in user_fks:
                batch.drop_constraint("fk_users_created_by_id_users", type_="foreignkey")
            if ("department_id",) in user_fks:
                batch.drop_constraint("fk_users_department_id_departments", type_="foreignkey")
            if ("legal_name_exception_approved_by_id",) in user_fks:
                batch.drop_constraint(
                    "fk_users_legal_name_exception_approved_by_id_users",
                    type_="foreignkey",
                )
            for name in user_columns:
                batch.drop_column(name)
    else:
        with op.batch_alter_table("document_template_versions") as batch:
            batch.drop_index("ix_document_template_versions_validated_by_id")
            batch.drop_constraint("fk_template_validated_by", type_="foreignkey")
            for name in template_columns:
                batch.drop_column(name)
        with op.batch_alter_table("users") as batch:
            batch.drop_index("ix_users_created_by_id")
            batch.drop_index("ix_users_department_id")
            batch.drop_index("ix_users_legal_name_exception_approved_by_id")
            batch.drop_constraint("fk_users_created_by", type_="foreignkey")
            batch.drop_constraint("fk_users_department", type_="foreignkey")
            batch.drop_constraint("fk_users_legal_name_exception_approved_by", type_="foreignkey")
            for name in user_columns:
                batch.drop_column(name)
