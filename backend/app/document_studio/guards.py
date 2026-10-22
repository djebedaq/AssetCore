"""Database enforcement for immutable Studio versions and activation evidence."""
from sqlalchemy import DDL, event


def statements(dialect):
    pg = dialect == "postgresql"
    result = []
    for table in ("document_template_versions", "studio_activations", "company_brand_images"):
        condition = ("OLD.is_published AND OLD.layout_contract->>'studio' = '1'" if pg
                     else "OLD.is_published = 1 AND json_extract(OLD.layout_contract, '$.studio') = 1") if table == "document_template_versions" else "TRUE"
        for operation in ("UPDATE", "DELETE"):
            name = f"freeze_studio_{table}_{operation.lower()}"
            if pg:
                result.append(f"CREATE OR REPLACE FUNCTION {name}() RETURNS trigger AS $$ BEGIN "
                    f"IF {condition} THEN RAISE EXCEPTION 'immutable_studio_evidence'; END IF; "
                    "RETURN COALESCE(NEW, OLD); END; $$ LANGUAGE plpgsql")
                result.append(f"DROP TRIGGER IF EXISTS {name} ON {table}")
                result.append(f"CREATE TRIGGER {name} BEFORE {operation} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}()")
            else:
                result.append(f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {operation} ON {table} "
                    f"WHEN {condition} BEGIN SELECT RAISE(ABORT, 'immutable_studio_evidence'); END")
    return result


def install(metadata):
    def created(_target, connection, **kwargs):
        if connection.info.get("assetcore_schema_migration") or not any(t.name == "studio_activations" for t in kwargs.get("tables", [])):
            return
        for statement in statements(connection.dialect.name):
            connection.execute(DDL(statement))
    event.listen(metadata, "after_create", created)
