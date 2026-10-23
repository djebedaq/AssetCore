"""Proposal permissions, immutable review evidence and exact-version traceability."""
import base64
import copy
import hashlib
import io

import pytest
from app.document_studio import renderer
from app.models import (
    CompanyBrandImage,
    DocumentEditorDraft,
    DocumentTemplate,
    DocumentTemplateVersion,
    StudioActivation,
    StudioProposal,
    StudioProposalAttachment,
    StudioProposalDraft,
    StudioProposalEvent,
    User,
    utcnow,
)
from app.security import create_access_token
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_document_studio import image_payload
from test_document_studio_publication import manifest


def actor_headers(factory, role='director', suffix='one'):
    with factory() as db:
        owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        user = User(email=f'{role}-{suffix}@qa.invalid', full_name=f'Synthetic {role} {suffix}',
            password_hash=owner.password_hash, role=role, is_active=True, is_system_owner=False,
            first_name='QA', middle_name='Synthetic', last_name='Actor', job_title='QA reviewer', profile_status='PROFILE_COMPLETE')
        db.add(user)
        db.commit()
        return {'Authorization': 'Bearer ' + create_access_token(user)}


def studio_version(factory, number=100):
    with factory() as db:
        owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        template = db.scalar(select(DocumentTemplate).where(DocumentTemplate.document_type == 'PART_REQUEST'))
        data = manifest()
        data['layout']['blocks'].insert(0, {'id': 'exact_version', 'type': 'text', 'text': f'Synthetic version {number}'})
        source = renderer.build_source(data)
        item = DocumentTemplateVersion(template_id=template.id, version=number, language='bg', source_content=source,
            source_sha256=hashlib.sha256(source).hexdigest(), source_filename='qa-studio.docx',
            layout_contract={'studio': 1}, is_published=True, created_by_id=owner.id,
            validation_status='PASSED', published_at=utcnow())
        db.add(item)
        db.commit()
        return {'template_id': template.id, 'target_version_id': item.id, 'language': 'bg',
            'title': 'Synthetic header proposal', 'description': 'Move the synthetic logo and retain the document number.'}


def create(client, headers, payload):
    response = client.post('/api/studio/proposals', headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize('role,allowed', [('administrator', True), ('director', True), ('mechanic', False), ('observer', False)])
def test_proposal_role_matrix(client, auth_headers, session_factory, role, allowed):
    payload = studio_version(session_factory)
    headers = actor_headers(session_factory, role)
    response = client.post('/api/studio/proposals', headers=headers, json=payload)
    assert response.status_code == (201 if allowed else 403), response.text
    assert client.get('/api/studio/proposals', headers=headers).status_code == (200 if allowed else 403)
    if role == 'administrator':
        own = response.json()
        decision = client.post(f"/api/studio/proposals/{own['id']}/decision", headers=headers,
            json={'expected_revision': 1, 'status': 'ACCEPTED', 'reason': 'Non-owner administrator review'})
        assert decision.status_code == 200
        draft = client.post(f"/api/studio/proposals/{own['id']}/drafts", headers=headers,
            json={'expected_revision': 2, 'title': 'Non-owner administrator exact draft'})
        assert draft.status_code == 201 and draft.json()['base_version_id'] == payload['target_version_id']
        image = {k: v for k, v in image_payload().items() if k != 'purpose'}
        delegated = create(client, actor_headers(session_factory, suffix='delegated'), payload | {'attachments': [image]})
        path = f"/api/studio/proposals/{delegated['id']}"
        assert client.get(path, headers=headers).status_code == 200
        assert client.get('/api' + delegated['attachments'][0]['download_endpoint'], headers=headers).status_code == 200
        assert client.post(path + '/comments', headers=headers,
            json={'expected_revision': 1, 'body': 'Non-owner administrator comment'}).status_code == 201
        rejected = client.post(path + '/decision', headers=headers,
            json={'expected_revision': 2, 'status': 'REJECTED', 'reason': 'Non-owner administrator rejection'})
        assert rejected.status_code == 200 and rejected.json()['status'] == 'REJECTED'
    if role != 'administrator':
        # Protected template mutations are separate endpoints and permissions.
        for path, body in [('templates/1/drafts', {'title': 'Forbidden'}),
            ('drafts/1/publish', {'expected_revision': 1, 'receipt': 'x' * 65, 'change_note': 'Forbidden'}),
            ('versions/1/activate', {'reason': 'Forbidden'}),
            ('selections/PART_REQUEST/bg/restore-legacy', {'expected_revision': 0, 'expected_version_id': None, 'reason': 'Forbidden', 'confirmed': True})]:
            assert client.post('/api/studio/' + path, headers=headers, json=body).status_code == 403
        if allowed:
            p = response.json()
            assert client.post(f"/api/studio/proposals/{p['id']}/decision", headers=headers,
                json={'expected_revision': 1, 'status': 'ACCEPTED', 'reason': 'Forbidden decision'}).status_code == 403
            assert client.post(f"/api/studio/proposals/{p['id']}/drafts", headers=headers,
                json={'expected_revision': 1, 'title': 'Forbidden editor'}).status_code == 403


def test_owner_decisions_do_not_publish_and_stale_decisions_conflict(client, auth_headers, session_factory):
    director = actor_headers(session_factory)
    p = create(client, director, studio_version(session_factory))
    with session_factory() as db:
        count = db.scalar(select(func.count(DocumentTemplateVersion.id)))
    endpoint = f"/api/studio/proposals/{p['id']}"
    for reason in ('', '  '):
        assert client.post(endpoint + '/decision', headers=auth_headers,
            json={'expected_revision': 1, 'status': 'ACCEPTED', 'reason': reason}).status_code == 422
    result = client.post(endpoint + '/decision', headers=auth_headers,
        json={'expected_revision': 1, 'status': 'ACCEPTED', 'reason': 'Approved for editor review'})
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'ACCEPTED' and result.json()['revision'] == 2
    assert client.post(endpoint + '/decision', headers=auth_headers,
        json={'expected_revision': 1, 'status': 'REJECTED', 'reason': 'Stale competing decision'}).status_code == 409
    with session_factory() as db:
        assert db.scalar(select(func.count(DocumentTemplateVersion.id))) == count
        assert db.scalar(select(func.count(DocumentEditorDraft.id))) == 0
        assert db.scalar(select(func.count(StudioActivation.id))) == 0
        assert [e.kind for e in db.scalars(select(StudioProposalEvent).order_by(StudioProposalEvent.revision))] == ['CREATED', 'ACCEPTED']


def test_own_scope_idor_and_safe_attachment_never_becomes_brand_image(client, auth_headers, session_factory):
    first, other = actor_headers(session_factory), actor_headers(session_factory, suffix='two')
    payload = studio_version(session_factory)
    image = image_payload()
    image.pop('purpose')
    image['content_base64'] = base64.b64encode(base64.b64decode(image['content_base64']) + b'<script>must disappear</script>').decode()
    p = create(client, first, payload | {'attachments': [image]})
    path = f"/api/studio/proposals/{p['id']}"
    image_path = '/api' + p['attachments'][0]['download_endpoint']
    assert client.get(path).status_code == 401
    assert client.post('/api/studio/proposals', json=payload).status_code == 401
    assert client.get(path, headers=other).status_code == 404
    assert client.get(image_path, headers=other).status_code == 404
    assert client.post(path + '/comments', headers=other, json={'expected_revision': 1, 'body': 'Forbidden comment'}).status_code == 404
    assert client.get('/api/studio/proposals', headers=other).json()['total'] == 0
    assert client.get('/api/studio/proposals', headers=auth_headers).json()['pending_count'] == 1
    result = client.get(image_path, headers=first)
    assert result.status_code == 200 and result.headers['content-type'] == 'image/png'
    assert b'<script>' not in result.content and 'no-store' in result.headers['cache-control']
    assert hashlib.sha256(result.content).hexdigest() == p['attachments'][0]['sha256']
    second = create(client, other, payload)
    assert client.get(f"/api/studio/proposals/{second['id']}/attachments/{p['attachments'][0]['id']}", headers=other).status_code == 404
    assert client.get(image_path.replace('/attachments/', '/attachments/999'), headers=first).status_code == 404
    with session_factory() as db:
        assert db.scalar(select(func.count(CompanyBrandImage.id))) == 0
    comment = client.post(path + '/comments', headers=first, json={'expected_revision': 1, 'body': '<script>alert("escaped by UI")</script>'})
    assert comment.status_code == 201 and comment.json()['revision'] == 2
    assert client.post(path + '/comments', headers=first, json={'expected_revision': 1, 'body': 'Stale comment'}).status_code == 409


def test_history_pagination_is_bounded_scoped_and_append_only(client, auth_headers, session_factory):
    from app.document_studio import proposals
    director = actor_headers(session_factory)
    p = create(client, director, studio_version(session_factory))
    with session_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        item = db.get(StudioProposal, p['id'])
        for revision in range(1, 106):
            proposals.advance(db, item, revision)
            proposals.event(db, item, actor, 'COMMENT', f'Synthetic bounded history {revision}')
        db.commit()
    path = f"/api/studio/proposals/{p['id']}"
    latest = client.get(path, headers=director).json()
    assert len(latest['events']) == 100 and latest['revision'] == 106 and latest['events_before'] == 7
    older = client.get(path + '?before_revision=7', headers=director).json()
    assert [e['revision'] for e in older['events']] == list(range(1, 7)) and older['events_before'] is None
    assert len({e['id'] for e in latest['events'] + older['events']}) == 106
    assert client.get(path + '?before_revision=7', headers=actor_headers(session_factory, suffix='other')).status_code == 404


def test_proposal_search_cyrillic_filters_and_literal_metacharacters(client, auth_headers, session_factory):
    payload = studio_version(session_factory)
    director = actor_headers(session_factory)
    create(client, director, payload | {'title': 'ПРОМЯНА НА ШАПКАТА — ИЗМЕНЕНИЕ 50%'})
    for query in ('промяна', 'изменение', '50%'):
        result = client.get('/api/studio/proposals', headers=director, params={'q': query, 'status': 'PENDING', 'language': 'bg'})
        assert result.status_code == 200 and result.json()['total'] == 1, result.text
    assert client.get('/api/studio/proposals', headers=director, params={'q': "' OR 1=1 --"}).json()['total'] == 0
    assert client.get('/api/studio/proposals', headers=director, params={'q': '_%_'}).json()['total'] == 0
    assert client.get('/api/studio/proposals', headers=director, params={'status': 'REJECTED'}).json()['total'] == 0
    assert client.get('/api/studio/proposals', headers=actor_headers(session_factory, suffix='search-other'), params={'q': 'промяна'}).json()['total'] == 0


@pytest.mark.parametrize('change', [
    {'description': ' '}, {'layout': {'blocks': []}}, {'status': 'ACCEPTED'}, {'target_version_id': 999999},
    {'language': 'ru'}, {'attachments': [image_payload()]},
    {'attachments': [dict(filename='../bad.png', media_type='image/png', content_base64='invalid')]},
    {'attachments': [dict(filename='active.svg', media_type='image/svg+xml', content_base64='aGVsbG8=')]},
    {'attachments': [dict(filename='fake.png', media_type='image/png', content_base64='aGVsbG8=')]},
    {'attachments': [dict(filename='x.png', media_type='image/png', content_base64='x' * 2_700_001)]},
    {'attachments': [dict(filename='x.png', media_type='image/png', content_base64='aGVsbG8=')] * 4},
])
def test_invalid_proposal_rejected_atomically(client, session_factory, change):
    payload = studio_version(session_factory)
    response = client.post('/api/studio/proposals', headers=actor_headers(session_factory), json=payload | change)
    assert response.status_code == 422, response.text
    with session_factory() as db:
        assert db.scalar(select(func.count(StudioProposal.id))) == 0
        assert db.scalar(select(func.count(StudioProposalAttachment.id))) == 0


def test_exact_draft_original_preserved_and_explicit_newer_choice(client, auth_headers, session_factory):
    payload = studio_version(session_factory)
    newer = studio_version(session_factory, 101)
    p = create(client, actor_headers(session_factory), payload)
    path = f"/api/studio/proposals/{p['id']}"
    assert p['newer_published']
    assert client.post(path + '/drafts', headers=auth_headers, json={'expected_revision': 1, 'title': 'Too early'}).status_code == 409
    client.post(path + '/decision', headers=auth_headers, json={'expected_revision': 1, 'status': 'ACCEPTED', 'reason': 'Proceed with controlled editing'})
    draft = client.post(path + '/drafts', headers=auth_headers, json={'expected_revision': 2, 'title': 'Exact version QA'})
    assert draft.status_code == 201, draft.text
    assert draft.json()['base_version_id'] == payload['target_version_id']
    assert draft.json()['layout']['blocks'][0]['text'] == 'Synthetic version 100'
    assert client.post(path + '/drafts', headers=auth_headers, json={'expected_revision': 2, 'title': 'Stale draft'}).status_code == 409
    explicit = client.post(path + '/drafts', headers=auth_headers, json={'expected_revision': 3, 'title': 'Explicit newer QA', 'base_version_id': newer['target_version_id']})
    assert explicit.status_code == 201 and explicit.json()['layout']['blocks'][0]['text'] == 'Synthetic version 101'
    detail = client.get(path, headers=auth_headers).json()
    assert detail['target_version_id'] == payload['target_version_id'] and len(detail['drafts']) == 2
    with session_factory() as db:
        assert db.get(DocumentTemplateVersion, payload['target_version_id']).source_sha256 == hashlib.sha256(db.get(DocumentTemplateVersion, payload['target_version_id']).source_content).hexdigest()
        assert db.scalar(select(func.count(StudioProposalDraft.id))) == 2


def test_reference_only_cannot_silently_create_unrelated_layout(client, auth_headers, session_factory):
    with session_factory() as db:
        v = db.scalar(select(DocumentTemplateVersion))
        payload = dict(template_id=v.template_id, target_version_id=v.id, language=v.language,
            title='Synthetic reference proposal', description='Reconstruct this controlled reference manually.')
    p = create(client, actor_headers(session_factory), payload)
    path = f"/api/studio/proposals/{p['id']}"
    client.post(path + '/decision', headers=auth_headers, json={'expected_revision': 1, 'status': 'ACCEPTED', 'reason': 'Requires manual reconstruction'})
    result = client.post(path + '/drafts', headers=auth_headers, json={'expected_revision': 2, 'title': 'Must not substitute'})
    assert result.status_code == 422 and result.json()['detail']['code'] == 'studio_proposal_reference_only'
    with session_factory() as db:
        assert db.scalar(select(func.count(DocumentEditorDraft.id))) == 0


@pytest.mark.parametrize('sql', [
    'UPDATE studio_proposals SET title = :value, revision = revision + 1',
    'UPDATE studio_proposals SET revision = revision + 2', 'DELETE FROM studio_proposals',
    'UPDATE studio_proposal_events SET body = :value', 'DELETE FROM studio_proposal_events',
    'UPDATE studio_proposal_attachments SET sha256 = :value', 'DELETE FROM studio_proposal_attachments',
])
def test_proposal_evidence_immutable_at_database_boundary(client, session_factory, sql):
    payload = studio_version(session_factory)
    image = image_payload()
    image.pop('purpose')
    create(client, actor_headers(session_factory), payload | {'attachments': [image]})
    with session_factory() as db, pytest.raises(DBAPIError, match='immutable_proposal_evidence'):
        db.execute(text(sql), {'value': 'tampering'})


def test_no_logo_placeholder_is_printed_and_compact_native_properties(session_factory):
    from app.document_studio.schemas import Layout
    from app.document_studio.starter_layouts import professional_layout
    from docx import Document
    from pydantic import ValidationError
    for language in ('bg', 'en', 'ru'):
        data = manifest(language=language)
        layout = professional_layout('PART_REQUEST', language).model_dump()
        for block in layout['blocks']:
            if block['type'] == 'dynamic_table':
                block.update(cell_padding_mm=.6, min_height_mm=4)
                block['style'].update(paragraph_before_mm=1, spacing_mm=.5)
        data['layout'] = layout
        values, tables = renderer.synthetic_values(language, 5)
        docx = renderer.render(data, values, tables)
        doc = Document(io.BytesIO(docx))
        xml = doc._element.xml + doc.sections[0].header._element.xml
        assert all(label not in xml for label in ('Фирмено лого', 'Company logo', 'Логотип компании'))
        assert 'w:tcMar' in xml and 'w:hRule="atLeast"' in xml
        assert renderer.manifest_from_source(docx)['layout'] == layout
        invalid = copy.deepcopy(layout)
        invalid['blocks'].append({'id': 'missing_image', 'type': 'image', 'image_id': None})
        with pytest.raises(ValidationError):
            Layout.model_validate(invalid)
