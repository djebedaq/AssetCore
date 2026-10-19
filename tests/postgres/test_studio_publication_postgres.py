"""PostgreSQL activation contention and database immutability; real rendering is
covered separately by test_document_studio_publication on the converter host."""
import pytest
from app.document_studio import renderer, routes
from app.document_studio.schemas import ActivationInput
from app.models import DocumentTemplate, DocumentTemplateVersion, StudioActivation, User, utcnow
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_concurrency import pg_factory as pg_factory  # noqa: F811
from test_concurrency import race
from test_document_studio_publication import manifest

pytestmark = pytest.mark.postgres


def test_postgres_immutable_studio_evidence_and_activation_cas(pg_factory):
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
    # Real concurrent transactions compete for the first selection revision.
    payload = ActivationInput(reason='Synthetic PostgreSQL QA')
    outcomes = race(pg_factory, DocumentTemplateVersion, ids[0],
        [lambda db, actor: routes.activate_version(ids[0], payload, actor, db),
         lambda db, actor: routes.activate_version(ids[1], payload, actor, db)], success_status=201)
    assert sorted(row.status for row in outcomes) == [201, 409]
    with pg_factory() as db:
        assert len(list(db.scalars(select(StudioActivation)))) == 1
    for sql in ('UPDATE document_template_versions SET change_note = :value WHERE id = :id',
                'DELETE FROM document_template_versions WHERE id = :id'):
        with pg_factory() as db, pytest.raises(DBAPIError, match='immutable_studio_evidence'):
            db.execute(text(sql), {'id': ids[0], 'value': 'must fail'})
    with pg_factory() as db, pytest.raises(DBAPIError, match='immutable_studio_evidence'):
        db.execute(text('UPDATE studio_activations SET reason = :value'), {'value': 'must fail'})
