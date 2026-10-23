"""Assert proposal decisions/drafts/publication cannot change signed evidence."""
import hashlib
import json
import pickle

from sqlalchemy import select


def verify_proposal_archive_preservation(client, headers, factory, output):
    from app.models import (
        GeneratedDocument,
        Machine,
        OfficialDocumentVersion,
        ProtocolDocument,
        RequestApprovalSnapshot,
        RequestNumberCounter,
        StudioActivation,
    )
    from test_document_studio_publication import publish
    from test_studio_proposals import actor_headers, create, studio_version

    tables = (Machine, OfficialDocumentVersion, GeneratedDocument, ProtocolDocument,
        RequestApprovalSnapshot, RequestNumberCounter, StudioActivation)

    def frozen():
        with factory() as db:
            return {model.__tablename__: hashlib.sha256(pickle.dumps([
                tuple(row) for row in db.execute(select(model.__table__).order_by(*model.__table__.primary_key.columns))
            ], protocol=5)).hexdigest() for model in tables}

    before = frozen()
    p = create(client, actor_headers(factory, suffix='archive-proof'), studio_version(factory))
    path = f"/api/studio/proposals/{p['id']}"
    decision = client.post(path + '/decision', headers=headers, json={'expected_revision': 1,
        'status': 'ACCEPTED', 'reason': 'Synthetic archive preservation review'})
    assert decision.status_code == 200, decision.text
    draft = client.post(path + '/drafts', headers=headers, json={'expected_revision': 2, 'title': 'Synthetic archive-safe follow-up'})
    assert draft.status_code == 201, draft.text
    version, _ = publish(client, headers, draft.json())
    after = frozen()
    assert before == after
    (output / 'proposal-archive-preservation.json').write_text(json.dumps({
        'passed': True, 'before_sha256': before, 'after_sha256': after,
        'proposal_id': p['id'], 'draft_id': draft.json()['id'], 'published_version_id': version['id'],
        'actions': ['submit', 'accept', 'clone exact version', 'real PDF preview', 'publish separately'],
        'scope': 'All rows and raw bytes in the disposable canonical four-workflow database; no production connection',
    }, indent=2) + '\n', encoding='utf-8')
