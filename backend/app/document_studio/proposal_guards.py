"""Append-only proposal evidence and immutable target/decision identity."""
from sqlalchemy import DDL, event

TABLES = ('studio_proposal_events', 'studio_proposal_attachments', 'studio_proposal_drafts')


def statements(dialect):
    pg = dialect == 'postgresql'
    output = []
    immutable = ('id', 'template_id', 'target_version_id', 'author_id', 'language', 'title', 'description', 'created_at')
    changed = ' OR '.join(f'NEW.{c} IS DISTINCT FROM OLD.{c}' if pg else f'NEW.{c} IS NOT OLD.{c}' for c in immutable)
    decision = ' OR '.join(f'NEW.{c} IS DISTINCT FROM OLD.{c}' if pg else f'NEW.{c} IS NOT OLD.{c}'
                           for c in ('status', 'decided_at', 'decided_by_id', 'decision_reason'))
    invalid = f"({changed}) OR NEW.revision != OLD.revision + 1 OR (OLD.status != 'PENDING' AND ({decision}))"
    for table in (*TABLES, 'studio_proposals'):
        for operation in ('UPDATE', 'DELETE'):
            condition = invalid if table == 'studio_proposals' and operation == 'UPDATE' else 'TRUE'
            name = f'freeze_{table}_{operation.lower()}'
            if pg:
                output += [f"CREATE OR REPLACE FUNCTION {name}() RETURNS trigger AS $$ BEGIN IF {condition} THEN "
                    "RAISE EXCEPTION 'immutable_proposal_evidence'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql",
                    f'DROP TRIGGER IF EXISTS {name} ON {table}',
                    f'CREATE TRIGGER {name} BEFORE {operation} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}()']
            else:
                output.append(f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {operation} ON {table} WHEN {condition} "
                              "BEGIN SELECT RAISE(ABORT, 'immutable_proposal_evidence'); END")
    return output


def install(metadata):
    def created(_target, connection, **kwargs):
        if connection.info.get('assetcore_schema_migration') or not any(t.name == 'studio_proposals' for t in kwargs.get('tables', [])):
            return
        for sql in statements(connection.dialect.name):
            connection.execute(DDL(sql))
    event.listen(metadata, 'after_create', created)
