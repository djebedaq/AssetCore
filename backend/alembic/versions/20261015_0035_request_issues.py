"""REQUESTS-01 additive schema; no historical renumbering or Float conversion.

Database guards are frozen in this revision, independently of application code.
"""

import re

import sqlalchemy as sa
from alembic import op

revision = "20261015_0035"
down_revision = "20261013_0034"
branch_labels = None
depends_on = None

LOCKED_REQUEST_FIELDS = (
    "machine_id",
    "repair_id",
    "repair_kit_id",
    "repair_kit_mode",
    "part_name",
    "part_number",
    "quantity",
    "reason",
    "priority",
    "request_reference",
    "language",
    "requested_by_id",
    "submitted_at",
    "decided_at",
    "decided_by_id",
    "decision_note",
    "department",
    "created_at",
    "request_kind",
)
LOCKED_LINE_FIELDS = (
    "request_id",
    "catalog_part_id",
    "position",
    "part_number",
    "description",
    "quantity",
    "exact_quantity",
    "delivered_quantity",
    "unit",
    "reason",
    "source_document",
    "source_page",
    "is_unknown_part",
    "assembly",
    "note",
    "linked_catalog_part_id",
    "linked_by_id",
    "linked_at",
    "link_note",
)


def statements(dialect: str) -> list[str]:
    pg = dialect == "postgresql"
    result = []

    def trigger(name, table, operation, condition):
        if pg:
            result.append(f"""CREATE FUNCTION {name}() RETURNS trigger AS $$
                BEGIN IF {condition} THEN RAISE EXCEPTION 'immutable_request_evidence';
                END IF; RETURN COALESCE(NEW, OLD); END; $$ LANGUAGE plpgsql""")
            result.append(
                f"CREATE TRIGGER {name} BEFORE {operation} ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION {name}()"
            )
        else:
            result.append(
                f"CREATE TRIGGER {name} BEFORE {operation} ON {table} "
                f"WHEN {condition} BEGIN SELECT RAISE(ABORT, "
                "'immutable_request_evidence'); END"
            )

    def different(fields):
        operator = "IS DISTINCT FROM" if pg else "IS NOT"
        return " OR ".join(f"NEW.{field} {operator} OLD.{field}" for field in fields)

    for table in ("request_approval_snapshots", "request_delivery_events"):
        for operation in ("UPDATE", "DELETE"):
            trigger(f"freeze_{table}_{operation.lower()}", table, operation, "TRUE")
    exists = "EXISTS (SELECT 1 FROM request_approval_snapshots WHERE request_id = OLD.id)"
    trigger(
        "freeze_request_fields",
        "part_requests",
        "UPDATE",
        f"{exists} AND ({different(LOCKED_REQUEST_FIELDS)})",
    )
    trigger("freeze_request_delete", "part_requests", "DELETE", exists)
    for table in ("part_request_lines", "part_request_attachments"):
        exists_old = (
            "EXISTS (SELECT 1 FROM request_approval_snapshots WHERE request_id = OLD.request_id)"
        )
        exists_new = (
            "EXISTS (SELECT 1 FROM request_approval_snapshots WHERE request_id = NEW.request_id)"
        )
        trigger(f"freeze_{table}_insert", table, "INSERT", exists_new)
        trigger(f"freeze_{table}_delete", table, "DELETE", exists_old)
        condition = f"({exists_old} OR {exists_new})"
        if table == "part_request_lines":
            condition += f" AND ({different(LOCKED_LINE_FIELDS)})"
        trigger(f"freeze_{table}_update", table, "UPDATE", condition)
    for operation in ("UPDATE", "DELETE"):
        trigger(
            f"freeze_kk_archive_{operation.lower()}",
            "generated_documents",
            operation,
            "EXISTS (SELECT 1 FROM request_approval_snapshots "
            "WHERE request_id = OLD.part_request_id)",
        )
    trigger("freeze_request_counter_delete", "request_number_counter", "DELETE", "TRUE")
    trigger(
        "freeze_request_counter_reset",
        "request_number_counter",
        "UPDATE",
        "NEW.id <> OLD.id OR NEW.next_value <> OLD.next_value + 1",
    )
    return result


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # An existing canonical KK number needs an explicit business resolution.
    # Fail closed before changing anything; never skip or overwrite history.
    for table, column in (
        ("official_documents", "document_number"),
        ("generated_documents", "document_number"),
        ("part_requests", "request_reference"),
    ):
        values = bind.execute(
            sa.text(
                f"SELECT UPPER(TRIM({column})) FROM {table} WHERE UPPER(TRIM({column})) LIKE 'KK%'"
            )
        )
        if any(
            re.fullmatch(r"KK[0-9]+", row[0] or "") and int(row[0][2:]) >= 1000 for row in values
        ):
            raise RuntimeError("REQUESTS01_HISTORICAL_KK_CONFLICT")
    if "request_approval_snapshots" in inspector.get_table_names():
        # The bootstrap creates current metadata for a fresh installation.
        return
    # Nullable additive fields preserve every historical row and binary document.
    columns = {
        "request_kind": "VARCHAR(20) NOT NULL DEFAULT 'CATALOG'",
        "generation_status": "VARCHAR(20)",
        "generation_error": "VARCHAR(80)",
        "cancelled_at": "TIMESTAMP WITH TIME ZONE"
        if bind.dialect.name == "postgresql"
        else "DATETIME",
        "cancelled_by_id": "INTEGER REFERENCES users(id)",
        "cancellation_reason": "TEXT",
        "replacement_request_id": "INTEGER REFERENCES part_requests(id)",
    }
    for name, ddl in columns.items():
        op.execute(sa.text(f"ALTER TABLE part_requests ADD COLUMN {name} {ddl}"))
    op.add_column("part_request_lines", sa.Column("exact_quantity", sa.String(32), nullable=True))
    op.create_table(
        "request_number_counter",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("next_value", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1 AND next_value >= 1000", name="ck_request_counter"),
    )
    op.create_table(
        "request_approval_snapshots",
        sa.Column(
            "request_id",
            sa.Integer(),
            sa.ForeignKey("part_requests.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("official_number", sa.String(80), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "template_version_id", sa.Integer(), sa.ForeignKey("document_template_versions.id")
        ),
        sa.Column("template_content", sa.LargeBinary()),
        sa.UniqueConstraint("number", name="uq_request_kk_number"),
        sa.UniqueConstraint("official_number", name="uq_request_official_number"),
        sa.CheckConstraint("number >= 1000", name="ck_request_kk_minimum"),
    )
    op.create_table(
        "request_delivery_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "request_id",
            sa.Integer(),
            sa.ForeignKey("part_requests.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("quantities", sa.JSON(), nullable=False),
        sa.Column("supplier", sa.String(255)),
        sa.Column("note", sa.Text()),
        sa.Column(
            "correction_of_id",
            sa.Integer(),
            sa.ForeignKey("request_delivery_events.id", ondelete="RESTRICT"),
        ),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "request_id", "idempotency_key", name="uq_request_delivery_idempotency"
        ),
        sa.UniqueConstraint("correction_of_id", name="uq_request_delivery_correction"),
    )
    op.create_index(
        "ix_request_delivery_events_request_id", "request_delivery_events", ["request_id"]
    )
    for sql in statements(bind.dialect.name):
        op.execute(sa.text(sql))


def downgrade():
    bind = op.get_bind()
    checks = (
        "SELECT 1 FROM request_approval_snapshots LIMIT 1",
        "SELECT 1 FROM request_delivery_events LIMIT 1",
        "SELECT 1 FROM request_number_counter WHERE next_value <> 1000 LIMIT 1",
        "SELECT 1 FROM part_request_lines WHERE exact_quantity IS NOT NULL LIMIT 1",
        "SELECT 1 FROM part_requests WHERE request_kind <> 'CATALOG' OR generation_status IS NOT NULL "
        "OR generation_error IS NOT NULL OR cancelled_at IS NOT NULL OR cancelled_by_id IS NOT NULL "
        "OR cancellation_reason IS NOT NULL OR replacement_request_id IS NOT NULL LIMIT 1",
    )
    if any(bind.execute(sa.text(sql)).first() for sql in checks):
        raise RuntimeError("REQUESTS01_ROLL_FORWARD_REQUIRED_PRESERVE_OFFICIAL_HISTORY")
    # Empty-feature rehearsal only. Never discard a number, exact quantity or event.
    for sql in statements(bind.dialect.name):
        match = re.search(r"CREATE TRIGGER (\w+).*? ON (\w+)", sql, re.S)
        if match:
            name, table = match.groups()
            suffix = f" ON {table}" if bind.dialect.name == "postgresql" else ""
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}{suffix}"))
    if bind.dialect.name == "postgresql":
        for sql in statements("postgresql"):
            match = re.search(r"CREATE FUNCTION (\w+)\(", sql)
            if match:
                op.execute(sa.text(f"DROP FUNCTION IF EXISTS {match.group(1)}()"))
    for table in (
        "request_delivery_events",
        "request_approval_snapshots",
        "request_number_counter",
    ):
        op.drop_table(table)
    columns = (
        "request_kind",
        "generation_status",
        "generation_error",
        "cancelled_at",
        "cancelled_by_id",
        "cancellation_reason",
        "replacement_request_id",
    )
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            "part_requests",
            naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
        ) as batch:
            batch.drop_constraint("fk_part_requests_cancelled_by_id_users", type_="foreignkey")
            batch.drop_constraint(
                "fk_part_requests_replacement_request_id_part_requests", type_="foreignkey"
            )
            for column in columns:
                batch.drop_column(column)
    else:
        for column in columns:
            op.drop_column("part_requests", column)
    op.drop_column("part_request_lines", "exact_quantity")
