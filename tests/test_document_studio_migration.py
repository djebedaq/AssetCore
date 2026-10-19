import importlib.util
from pathlib import Path

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.models import Base, User
from app.seed import seed_database
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session
from test_migrations import _run_sqlite_revision

TABLES = ('document_editor_drafts', 'company_profiles', 'company_brand_images')


def test_additive_upgrade_no_customer_identity_inference(tmp_path):
    path = tmp_path / 'studio-qa.db'
    _run_sqlite_revision(path, command.upgrade, '20261015_0035')
    engine = create_engine(f'sqlite:///{path.as_posix()}')
    with Session(engine) as db:
        seed_database(db)
        actor_id = db.scalar(select(User.id))
    with engine.begin() as connection:
        for table in TABLES:
            connection.execute(text(f'DROP TABLE {table}'))
        before = {name: list(connection.execute(text(f'SELECT * FROM {name}')).fetchall())
                  for name in ('machines', 'document_templates', 'document_template_versions', 'audit_logs')}
    _run_sqlite_revision(path, command.upgrade, 'head')
    engine.dispose()
    with engine.connect() as connection:
        for table in TABLES:
            assert connection.scalar(text(f'SELECT count(*) FROM {table}')) == 0
            assert {c['name'] for c in inspect(connection).get_columns(table)} == set(Base.metadata.tables[table].columns.keys())
        for table, records in before.items():
            assert list(connection.execute(text(f'SELECT * FROM {table}')).fetchall()) == records
    revision = Path(__file__).resolve().parents[1] / 'backend/alembic/versions/20261019_0036_document_studio.py'
    spec = importlib.util.spec_from_file_location('studio_qa_migration', revision)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        connection.execute(text('INSERT INTO company_profiles (id,revision,identity,updated_by_id,updated_at) '
                                "VALUES (1,1,'{}',:actor,CURRENT_TIMESTAMP)"), {'actor': actor_id})
    with engine.begin() as connection, pytest.raises(RuntimeError, match='history cannot be discarded'):
        with Operations.context(MigrationContext.configure(connection)):
            module.downgrade()
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM company_profiles')) == 1
    engine.dispose()
