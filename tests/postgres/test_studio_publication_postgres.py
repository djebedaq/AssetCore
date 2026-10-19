"""PostgreSQL activation contention and database immutability; real rendering is
covered separately by test_document_studio_publication on the converter host."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.document_studio import publication, renderer, routes
from app.document_studio.schemas import ActivationInput
from app.models import DocumentTemplate, DocumentTemplateVersion, StudioActivation, User, utcnow
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_concurrency import pg_factory as pg_factory  # noqa: F811
from test_document_studio_publication import manifest

pytestmark = pytest.mark.postgres


def test_postgres_immutable_studio_evidence_and_activation_cas(pg_factory, monkeypatch):
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        template = db.scalar(select(DocumentTemplate).where(DocumentTemplate.document_type == 'PART_REQUEST'))
        source = renderer.build_source(manifest())
        ids = []
        for number in (100, 101):
            version = DocumentTemplateVersion(template_id=template.id, version=number, language='bg',
                source_content=source, source_sha256=renderer.digest(source), source_filename='studio-template.docx',
                layout_contract={'studio': 1}, created_by_id=actor.id, validation_status='PASSED',
                validation_report={'valid': True}, is_published=True, published_by_id=actor.id, published_at=utcnow())
            db.add(version)
            db.flush()
            ids.append(version.id)
        db.commit()
    # Both transactions read the same absent selection before either writes.
    # The unique revision constraint, rather than unrelated row locks, decides
    # which activation wins. The losing transaction must roll back its audit.
    barrier = Barrier(2)
    original_selection = publication.active_selection
    def overlapping_selection(*args):
        selected = original_selection(*args)
        barrier.wait(timeout=30)
        return selected
    monkeypatch.setattr(publication, 'active_selection', overlapping_selection)
    payload = ActivationInput(reason='Synthetic PostgreSQL QA')
    def activate(version_id):
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            try:
                routes.activate_version(version_id, payload, actor, db)
                return 201
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(activate, ids))
    assert sorted(outcomes) == [201, 409]
    with pg_factory() as db:
        assert len(list(db.scalars(select(StudioActivation)))) == 1
    for sql in ('UPDATE document_template_versions SET change_note = :value WHERE id = :id',
                'DELETE FROM document_template_versions WHERE id = :id'):
        with pg_factory() as db, pytest.raises(DBAPIError, match='immutable_studio_evidence'):
            db.execute(text(sql), {'id': ids[0], 'value': 'must fail'})
    with pg_factory() as db, pytest.raises(DBAPIError, match='immutable_studio_evidence'):
        db.execute(text('UPDATE studio_activations SET reason = :value'), {'value': 'must fail'})
