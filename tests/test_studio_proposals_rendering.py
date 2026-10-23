"""Proposal publication trace through the existing real DOCX/PDF pipeline."""
import io

import fitz
from app.models import DocumentTemplateVersion, StudioActivation
from docx import Document
from sqlalchemy import func, select
from test_document_studio_publication import converter as converter  # noqa: F811
from test_document_studio_publication import publish
from test_studio_proposals import actor_headers, create, studio_version


def test_accepted_proposal_publishes_separately_with_exact_trace(converter, client, auth_headers, session_factory):
    payload = studio_version(session_factory)
    director = actor_headers(session_factory)
    proposal = create(client, director, payload)
    path = f"/api/studio/proposals/{proposal['id']}"
    decision = client.post(path + '/decision', headers=auth_headers, json={
        'expected_revision': 1, 'status': 'ACCEPTED', 'reason': 'Synthetic separate editor acceptance'})
    assert decision.status_code == 200
    result = client.post(path + '/drafts', headers=auth_headers, json={'expected_revision': 2, 'title': 'Synthetic linked editor draft'})
    assert result.status_code == 201, result.text
    preview = client.post(f"/api/studio/drafts/{result.json()['id']}/preview", headers=auth_headers,
        json={'expected_revision': result.json()['revision'], 'rows': 5}).json()
    version, _ = publish(client, auth_headers, result.json())
    detail = client.get(path, headers=director).json()
    assert detail['status'] == 'ACCEPTED' and detail['target_version_id'] == payload['target_version_id']
    assert detail['events'][-1]['kind'] == 'PUBLISHED'
    assert detail['events'][-1]['version_id'] == version['id']
    assert detail['events'][-1]['draft_id'] == result.json()['id']
    assert detail['revision'] == 4 and len(detail['drafts']) == 1
    with session_factory() as db:
        assert db.get(DocumentTemplateVersion, version['id']).is_published
        assert db.scalar(select(func.count(StudioActivation.id))) == 0
    # Directors preview that specific immutable version without editing a draft.
    rendered = client.get(f"/api/studio/versions/{version['id']}/preview", headers=director)
    assert rendered.status_code == 200 and rendered.json()['report']['docx_sha256'] == preview['report']['docx_sha256']


def test_published_starter_missing_logo_actual_pdf(converter, client, auth_headers, session_factory):
    # The same validated manifest and renderer feed the canonical workflows.
    # Actual official archives are checked separately in the four-workflow test.
    import base64

    from test_document_studio_publication import make_draft
    draft = make_draft(client, auth_headers)
    version, preview = publish(client, auth_headers, draft)
    docx = base64.b64decode(preview['docx'])
    pdf = base64.b64decode(preview['pdf'])
    document = Document(io.BytesIO(docx))
    assert 'Фирмено лого' not in document.sections[0].header._element.xml
    with fitz.open(stream=pdf, filetype='pdf') as rendered:
        assert 'Фирмено лого' not in '\n'.join(page.get_text() for page in rendered)
    assert version['active'] is False
