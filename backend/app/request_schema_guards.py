"""Database defence for approved fields and append-only request evidence."""

from sqlalchemy import DDL, event

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


def install(metadata):
    def created(_target, connection, **kwargs):
        # Published bootstrap migrations call create_all(checkfirst=True) more than once.
        # Metadata events also fire when no table was created.
        if not any(
            table.name == "request_approval_snapshots" for table in kwargs.get("tables", [])
        ):
            return
        for statement in statements(connection.dialect.name):
            connection.execute(DDL(statement))

    event.listen(metadata, "after_create", created)
