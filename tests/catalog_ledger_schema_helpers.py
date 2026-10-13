"""Compare migrated durable-ledger constraints/indexes on SQLite and PostgreSQL."""
from app.models import Base
from sqlalchemy import CheckConstraint, UniqueConstraint, inspect

TABLES = ("catalog_extraction_sessions", "catalog_extraction_sources", "catalog_extraction_attempts",
    "catalog_extraction_candidates", "catalog_source_review_decisions")


def assert_ledger_schema(connection):
    inspector = inspect(connection)
    for name in TABLES:
        table = Base.metadata.tables[name]
        expected_indexes = {(index.name, tuple(column.name for column in index.columns), bool(index.unique))
            for index in table.indexes}
        actual_indexes = {(index["name"], tuple(index["column_names"]), bool(index["unique"]))
            for index in inspector.get_indexes(name) if not index.get("duplicates_constraint")}
        assert expected_indexes == actual_indexes, (name, expected_indexes - actual_indexes, actual_indexes - expected_indexes)
        assert {(constraint.name, tuple(column.name for column in constraint.columns))
            for constraint in table.constraints if isinstance(constraint, UniqueConstraint)} == {
                (constraint["name"], tuple(constraint["column_names"])) for constraint in inspector.get_unique_constraints(name)}
        assert {constraint.name for constraint in table.constraints if isinstance(constraint, CheckConstraint)} == {
            constraint["name"] for constraint in inspector.get_check_constraints(name)}
        assert {(tuple(column.name for column in constraint.columns), constraint.referred_table.name,
            tuple(element.column.name for element in constraint.elements), constraint.ondelete)
            for constraint in table.foreign_key_constraints} == {
                (tuple(constraint["constrained_columns"]), constraint["referred_table"],
                    tuple(constraint["referred_columns"]), constraint.get("options", {}).get("ondelete"))
                for constraint in inspector.get_foreign_keys(name)}
