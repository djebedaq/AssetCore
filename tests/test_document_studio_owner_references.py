"""Studio authorship is protected history, including ordinary administrators."""

from app.document_studio.schemas import initial_layout
from app.models import (
    CompanyBrandImage,
    CompanyProfile,
    DocumentEditorDraft,
    DocumentTemplate,
    User,
)
from test_owner_data_deletion import deletion_client as deletion_client  # noqa: F811
from test_owner_data_deletion import deletion_factory as deletion_factory  # noqa: F811
from test_owner_data_deletion import execute, preview, user


def test_owner_cannot_delete_a_studio_author_or_cascade_studio_history(deletion_client, deletion_factory):
    identifier = user(deletion_factory, 'administrator')
    with deletion_factory() as db:
        db.add(CompanyProfile(id=1, revision=1, identity={'legal_name': 'Synthetic QA'}, updated_by_id=identifier))
        db.add(CompanyBrandImage(purpose='PRIMARY', filename='qa.png', content=b'QA retained evidence',
            sha256='a' * 64, width=1, height=1, created_by_id=identifier))
        template = DocumentTemplate(code='QA_STUDIO_OWNER', document_type='PART_REQUEST', name_bg='QA')
        db.add(template)
        db.flush()
        draft = DocumentEditorDraft(template_id=template.id, title='QA retained draft', language='bg',
            layout=initial_layout('PART_REQUEST').model_dump(), created_by_id=identifier, updated_by_id=identifier)
        db.add(draft)
        db.commit()
        draft_id = draft.id
    response = preview(deletion_client, 'user', identifier)
    assert response.status_code == 200
    data = response.json()
    assert not data['can_delete']
    blockers = {item['code']: item for item in data['blockers']}
    for table, label in [('company_profiles', 'companyProfiles'), ('company_brand_images', 'companyImages'),
                         ('document_editor_drafts', 'editorDrafts')]:
        assert blockers[table]['count'] == 1
        assert blockers[table]['label_key'] == f'ownerDeletion.references.{label}'
    assert execute(deletion_client, 'user', identifier, data['confirmation_text']).status_code == 409
    with deletion_factory() as db:
        assert db.get(User, identifier) is not None
        assert db.get(CompanyProfile, 1).revision == 1
        assert db.get(DocumentEditorDraft, draft_id).title == 'QA retained draft'
