"""Actual overlapping PostgreSQL reviews in independently migrated QA schemas."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.document_studio import proposals
from app.models import StudioProposal, StudioProposalEvent, User
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_concurrency import pg_factory as pg_factory  # noqa: F811
from test_studio_proposals import studio_version

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize('competing', ['decision', 'comment'])
def test_overlapping_proposal_decisions_and_comments_cas(pg_factory, monkeypatch, competing):
    payload = studio_version(pg_factory)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        p = proposals.create_proposal(proposals.ProposalInput(**payload), actor, db)
        proposal_id = p['id']
    barrier = Barrier(2)
    original = proposals.advance

    def overlap(*args, **kwargs):
        barrier.wait(timeout=30)
        return original(*args, **kwargs)

    monkeypatch.setattr(proposals, 'advance', overlap)

    def perform(index):
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            try:
                if competing == 'comment' and index:
                    proposals.comment(proposal_id, proposals.CommentInput(expected_revision=1, body='Overlapping QA comment'), actor, db)
                else:
                    proposals.decide(proposal_id, proposals.DecisionInput(expected_revision=1,
                        status='ACCEPTED' if not index else 'REJECTED', reason='Independent concurrent QA review'), actor, db)
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(perform, range(2))) == [200, 409]
    with pg_factory() as db:
        assert db.get(StudioProposal, proposal_id).revision == 2
        assert [event.revision for event in db.scalars(select(StudioProposalEvent).where(
            StudioProposalEvent.proposal_id == proposal_id).order_by(StudioProposalEvent.revision))] == [1, 2]
    for sql in ('UPDATE studio_proposal_events SET body = :body',
                'UPDATE studio_proposals SET title = :body, revision = revision + 1',
                'DELETE FROM studio_proposals'):
        with pg_factory() as db, pytest.raises(DBAPIError, match='immutable_proposal_evidence'):
            db.execute(text(sql), {'body': 'Forbidden evidence edit'})
