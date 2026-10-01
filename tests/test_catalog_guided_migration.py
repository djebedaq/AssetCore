"""Real SQLite 0030 upgrade preserves legacy inline PDF evidence exactly."""

from alembic import command
from app.models import (
    CatalogDefinition,
    CatalogRevision,
    CatalogRevisionArtifact,
    CatalogRevisionAssembly,
    User,
)
from app.seed import seed_database
from catalog_extraction_fixtures import manual
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from test_migrations import _run_sqlite_revision


def test_existing_0030_inline_bytes_remain_readable_and_untouched(tmp_path):
    path = tmp_path / 'qa-ingest-migration.db'
    _run_sqlite_revision(path, command.upgrade, 'head')
    engine = create_engine(f'sqlite:///{path}')
    original = manual()
    with Session(engine) as db:
        seed_database(db)
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        import hashlib
        catalog = CatalogDefinition(code='QA_SCHEMA', asset_category_id=1,
            name_bg='QA', name_en='QA', name_ru='QA', created_by_id=actor.id)
        db.add(catalog)
        db.flush()
        revision = CatalogRevision(catalog_id=catalog.id, revision_code='QA', created_by_id=actor.id)
        db.add(revision)
        db.flush()
        group = CatalogRevisionAssembly(revision_id=revision.id, code='QA',
            name_bg='QA', name_en='QA', name_ru='QA', created_by_id=actor.id)
        db.add(group)
        db.flush()
        artifact = CatalogRevisionArtifact(assembly_id=group.id, title='QA', filename='qa.pdf',
            media_type='application/pdf', content=original, sha256=hashlib.sha256(original).hexdigest(),
            page_count=2, created_by_id=actor.id)
        db.add(artifact)
        db.commit()
        artifact_id = artifact.id
    engine.dispose()
    _run_sqlite_revision(path, command.downgrade, '20260930_0030')
    engine = create_engine(f'sqlite:///{path}')
    with engine.connect() as connection:
        before = connection.execute(text('SELECT id,content,sha256,page_count FROM catalog_revision_artifacts')).all()
        assert before[0].content == original
    engine.dispose()
    _run_sqlite_revision(path, command.upgrade, 'head')
    engine = create_engine(f'sqlite:///{path}')
    with engine.connect() as connection:
        assert connection.execute(text('SELECT id,content,sha256,page_count FROM catalog_revision_artifacts')).all() == before
        assert connection.scalar(text('SELECT count(*) FROM machines')) == 19
    with Session(engine) as db:
        source = db.get(CatalogRevisionArtifact, artifact_id)
        assert source.source_blob_id is None and source.content == original
    engine.dispose()
