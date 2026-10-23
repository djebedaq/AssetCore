"""Additive SQLite upgrade preserves existing bytes and refuses history loss."""
import sqlite3

import pytest
from alembic import command
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from test_migrations import _run_sqlite_revision


def test_0039_upgrade_and_protected_history_downgrade(tmp_path):
    from app.models import DocumentTemplateVersion, StudioProposal, StudioProposalEvent, User
    from app.seed import seed_database
    path = tmp_path / 'proposal-migration.db'
    _run_sqlite_revision(path, command.upgrade, '20261019_0038')
    engine = create_engine('sqlite:///' + path.as_posix())
    with Session(engine) as db:
        seed_database(db)
        versions = [(v.id, v.source_content, v.source_sha256, v.source_path) for v in db.scalars(select(DocumentTemplateVersion))]
    _run_sqlite_revision(path, command.upgrade, 'head')
    with Session(engine) as db:
        assert versions == [(v.id, v.source_content, v.source_sha256, v.source_path) for v in db.scalars(select(DocumentTemplateVersion))]
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        version = db.scalar(select(DocumentTemplateVersion))
        p = StudioProposal(template_id=version.template_id, target_version_id=version.id, language=version.language,
            title='Synthetic migrated review', description='Synthetic proposal in a disposable QA database', author_id=actor.id)
        db.add(p)
        db.flush()
        db.add(StudioProposalEvent(proposal_id=p.id, revision=1, kind='CREATED', body=p.description, author_id=actor.id))
        db.commit()
    with pytest.raises(RuntimeError, match='Proposal history cannot be discarded'):
        _run_sqlite_revision(path, command.downgrade, '20261019_0038')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM studio_proposal_events').fetchone()[0] == 1
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '20261023_0039'
        with pytest.raises(sqlite3.IntegrityError, match='immutable_proposal_evidence'):
            db.execute('DELETE FROM studio_proposal_events')
    engine.dispose()
