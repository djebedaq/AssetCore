"""Immutable visual history DDL; Alembic contains a frozen copy for deployment."""

from sqlalchemy import DDL, event


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


def install_metadata_guards(table) -> None:
    for dialect in ("sqlite", "postgresql"):
        for statement in guard_statements(dialect):
            event.listen(table, "after_create", DDL(statement).execute_if(dialect=dialect))
    for function in ("check_part_visual_ordinal", "reject_part_visual_mutation"):
        event.listen(
            table,
            "after_drop",
            DDL(f"DROP FUNCTION IF EXISTS {function}() CASCADE").execute_if(dialect="postgresql"),
        )
