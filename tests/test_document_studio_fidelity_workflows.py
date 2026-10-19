"""Four actual workflows using isolated synthetic equipment and frozen archives."""
import json
import os
import shutil
from pathlib import Path

import fitz
import pytest
from app.document_studio.renderer import digest, manifest_from_source
from app.models import (
    CatalogVisualPartMap,
    CatalogVisualSource,
    Machine,
    OfficialDocument,
    OfficialDocumentVersion,
    PartCatalog,
    User,
)
from sqlalchemy import select


def test_professional_four_workflows_signing_and_controlled_appendices(
    client, auth_headers, machine_ids, issue_payload, finalize_signatures, session_factory, tmp_path, monkeypatch,
):
    if os.name == 'nt' or not shutil.which('libreoffice'):
        pytest.skip('Real bounded conversion runs on Linux/Docker and CI')
    from test_document_studio_publication import (
        test_real_canonical_issue_return_sign_repair_and_kk_use_selected_studio_sources,
    )

    part_id = client.get('/api/catalog/parts', headers=auth_headers).json()[0]['id']
    with session_factory() as db:
        original_ids = {m.id for m in db.scalars(select(Machine))}
        category_id = db.get(Machine, machine_ids['9']).category_id
        synthetic_ids = {}
        for code in ('4', '8', '9'):
            machine = Machine(inventory_number=f'SYNTHETIC-QA-{code}', name='SYNTHETIC QA ONLY',
                category='SYNTHETIC QA CATEGORY', category_id=category_id, brand='SYNTHETIC QA MANUFACTURER',
                manufacturer='SYNTHETIC QA MANUFACTURER', model='SYNTHETIC QA MODEL', serial_number=f'SYNTHETIC-QA-SERIAL-{code}',
                pressure_bar=500, status='READY', ownership='SYNTHETIC QA ONLY')
            db.add(machine)
            db.flush()
            synthetic_ids[code] = machine.id
        from app.catalog.references import ReferenceCreate, create
        part = db.get(PartCatalog, part_id)
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        scheme = db.scalar(select(CatalogVisualSource).where(CatalogVisualSource.source_id == part.source_id,
            CatalogVisualSource.role == 'EXPLODED_SCHEME'))
        parts_list = db.scalar(select(CatalogVisualSource).join(CatalogVisualPartMap,
            CatalogVisualPartMap.visual_source_id == CatalogVisualSource.id).where(CatalogVisualPartMap.part_id == part_id,
                CatalogVisualSource.role == 'SPARE_PARTS_LIST'))
        assert scheme is not None and parts_list is not None
        # Audited approval in this disposable QA DB, through the existing
        # compatibility service; verified source parts are never modified.
        create(db, actor, ReferenceCreate(machine_ids=[synthetic_ids['9']], scheme_id=scheme.id,
            parts_list_id=parts_list.id, part_ids=[part_id], source_revision=scheme.catalog_revision,
            compatibility_confirmed=True, reason='SYNTHETIC QA ONLY isolated reference approval'))
        db.commit()
    output = Path(os.environ.get('ASSETCORE_STUDIO_FIDELITY_WORKFLOW_OUTPUT', str(tmp_path)))
    monkeypatch.setenv('ASSETCORE_STUDIO_QA_OUTPUT', str(tmp_path / 'intermediate'))
    test_real_canonical_issue_return_sign_repair_and_kk_use_selected_studio_sources(
        True, client, auth_headers, synthetic_ids, issue_payload, finalize_signatures, session_factory, tmp_path,
    )
    folders = {'TRANSFER_ISSUE': 'transfer-issue', 'TRANSFER_RETURN': 'transfer-return',
        'REPAIR_PROTOCOL': 'repair-protocol', 'PART_REQUEST': 'parts-request'}
    reports = []
    with session_factory() as db:
        assert original_ids <= {m.id for m in db.scalars(select(Machine))}
        documents = {}
        for version in db.scalars(select(OfficialDocumentVersion).order_by(OfficialDocumentVersion.id)):
            if manifest_from_source(version.docx_content) is not None:
                documents[db.get(OfficialDocument, version.document_id).document_type] = version
        assert set(documents) == set(folders)
        for workflow, version in documents.items():
            folder = output / folders[workflow]
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'official-synthetic.docx').write_bytes(version.docx_content)
            (folder / 'official-synthetic.pdf').write_bytes(version.pdf_content)
            with fitz.open(stream=version.pdf_content, filetype='pdf') as pdf:
                for i, page in enumerate(pdf, 1):
                    page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(folder / f'official-synthetic-page-{i}.png')
                text = '\n'.join(p.get_text() for p in pdf)
                assert 'SYNTHETIC-QA-' in text and '[[ASSETCORE_' not in text
                if workflow == 'PART_REQUEST':
                    assert len(pdf) >= 3  # Actual approved diagram and parts-list appendices.
                reports.append({'workflow': workflow, 'docx_sha256': digest(version.docx_content), 'pdf_sha256': digest(version.pdf_content),
                    'pages': len(pdf), 'template_version_id': version.template_version_id, 'archive_unchanged_after_profile_and_selection_change': True})
    (output / 'official-workflow-proof.json').write_text(json.dumps({'passed': True, 'cases': reports}, indent=2) + '\n', encoding='utf-8')
