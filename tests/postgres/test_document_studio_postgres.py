"""Real PostgreSQL CAS contention, schema and identity/draft round trips."""

import pytest
import test_document_studio as contracts
from app.document_studio import routes
from app.document_studio.schemas import DraftUpdate, IdentityUpdate, Layout
from app.models import CompanyProfile, DocumentEditorDraft, DocumentTemplate, User
from sqlalchemy import select
from test_concurrency import pg_factory as pg_factory  # noqa: F811
from test_concurrency import race

pytestmark = pytest.mark.postgres


def test_two_postgres_company_initializations(pg_factory):
    contracts.test_two_first_company_writers_only_one_commits(pg_factory)


def test_postgres_draft_cas_under_real_lock_contention(pg_factory):
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        template = db.scalar(select(DocumentTemplate))
        draft = routes.create_draft(template.id, routes.DraftCreate(title='QA PG'), actor, db)
    payload = DraftUpdate(expected_revision=1, title='QA PG changed', layout=Layout.model_validate(draft['layout']))
    outcomes = race(pg_factory, DocumentEditorDraft, draft['id'],
                    [lambda db, actor: routes.update_draft(draft['id'], payload, actor, db)] * 2,
                    success_status=200)
    assert sorted(row.status for row in outcomes) == [200, 409]


def test_postgres_company_cas_under_real_lock_contention(pg_factory):
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        routes.update_company(IdentityUpdate(expected_revision=0, identity={'legal_name': 'QA PG'}), actor, db)
    payload = IdentityUpdate(expected_revision=1, identity={'legal_name': 'QA PG updated'})
    outcomes = race(pg_factory, CompanyProfile, 1,
                    [lambda db, actor: routes.update_company(payload, actor, db)] * 2, success_status=200)
    assert sorted(row.status for row in outcomes) == [200, 409]
