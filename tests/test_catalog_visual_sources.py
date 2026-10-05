"""01B staging contracts are explicit and isolated from the verified catalog."""

import base64
import hashlib
import io
import json

from app.governance.owner_data_deletion import ResourceType, preview
from app.models import (
    AssetCategory,
    AuditLog,
    CatalogDefinition,
    CatalogRevision,
    CatalogRevisionArtifact,
    CatalogRevisionAssembly,
    CatalogRevisionVisualPage,
    CatalogVisualPartMap,
    CatalogVisualSource,
    PartCatalog,
    RepairKit,
    User,
)
from PIL import Image
from reportlab.pdfgen import canvas
from sqlalchemy import func, select

BASE = "/api/admin/catalog-builder"


def _pdf(pages=3):
    stream = io.BytesIO()
    document = canvas.Canvas(stream)
    for number in range(pages):
        document.drawString(60, 700, f"QA page {number + 1}")
        document.showPage()
    document.save()
    return stream.getvalue()


def _workspace(client, headers, factory):
    with factory() as db:
        category = AssetCategory(code="QA_VISUAL_CATEGORY", name_bg="QA", name_en="QA", name_ru="QA",
                                 capabilities=["HAS_PARTS_CATALOG"])
        db.add(category)
        db.commit()
        category_id = category.id
    catalog = client.post(f"{BASE}/catalogs", headers=headers, json={
        "code": "QA_VISUAL_CATALOG", "asset_category_id": category_id,
        "name_bg": "QA", "name_en": "QA", "name_ru": "QA",
    })
    assert catalog.status_code == 201, catalog.text
    catalog_id = catalog.json()["id"]
    revision = client.post(f"{BASE}/catalogs/{catalog_id}/revisions", headers=headers,
                           json={"revision_code": "A"})
    assert revision.status_code == 201, revision.text
    return catalog_id, revision.json()["id"]


def _assembly(client, headers, revision_id):
    return client.post(f"{BASE}/revisions/{revision_id}/assemblies", headers=headers, json={
        "code": "PUMP", "name_bg": "Помпа", "name_en": "Pump", "name_ru": "Насос",
        "sort_order": 1,
    })


def _upload(client, headers, assembly_id, pdf, *, filename="source.pdf", media_type="application/pdf"):
    return client.post(f"{BASE}/assemblies/{assembly_id}/artifacts", headers=headers, json={
        "title": "QA source", "filename": filename, "media_type": media_type,
        "content_base64": base64.b64encode(pdf).decode(),
    })


def test_explicit_roles_preview_and_isolation(client, auth_headers, viewer_headers, session_factory):
    with session_factory() as db:
        live_before = (db.scalar(select(func.count(CatalogVisualSource.id))),
                       db.scalar(select(func.count(CatalogVisualPartMap.id))))
    catalog_id, revision_id = _workspace(client, auth_headers, session_factory)
    assembly = _assembly(client, auth_headers, revision_id)
    assert assembly.status_code == 201, assembly.text
    assembly_id = assembly.json()["id"]
    assert _assembly(client, auth_headers, revision_id).json()["detail"]["code"] == "catalog_assembly_duplicate"
    assert client.patch(f"{BASE}/assemblies/{assembly_id}", headers=auth_headers,
                        json={"name_en": "Pump assembly", "sort_order": 2}).json()["name_en"] == "Pump assembly"
    pdf = _pdf()
    uploaded = _upload(client, auth_headers, assembly_id, pdf)
    assert uploaded.status_code == 201, uploaded.text
    artifact = uploaded.json()
    artifact_id = artifact["id"]
    assert artifact["sha256"] == hashlib.sha256(pdf).hexdigest()
    assert artifact["page_count"] == 3
    duplicate = _upload(client, auth_headers, assembly_id, pdf)
    assert duplicate.status_code == 409 and duplicate.json()["detail"]["artifact_id"] == artifact_id
    assert client.patch(f"{BASE}/assemblies/{assembly_id}", headers=auth_headers,
                        json={"code": "VALVE"}).json()["detail"]["code"] == "catalog_assembly_code_in_use"
    downloaded = client.get(f"{BASE}/artifacts/{artifact_id}/download", headers=auth_headers)
    assert downloaded.content == pdf
    assert "filename*=UTF-8''source.pdf" in downloaded.headers["content-disposition"]
    preview_response = client.get(f"{BASE}/artifacts/{artifact_id}/pages/1/preview", headers=auth_headers)
    assert preview_response.status_code == 200 and preview_response.content.startswith(b"\x89PNG")
    assert "no-store" in preview_response.headers["cache-control"]
    assert preview_response.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(preview_response.content)) as image:
        # Actual subprocess-rendered response, not a mocked PNG signature.
        assert image.width >= 1100 and image.height >= 1500
        assert image.width * image.height <= 4_000_000 + image.width + image.height
    for number in [2, 3]:
        response = client.get(f"{BASE}/artifacts/{artifact_id}/pages/{number}/preview", headers=auth_headers)
        assert response.status_code == 200
        with Image.open(io.BytesIO(response.content)) as image:
            image.verify()
    assert client.get(f"{BASE}/artifacts/{artifact_id}/pages/4/preview", headers=auth_headers).status_code == 404
    assert client.get(f"{BASE}/artifacts/{artifact_id}/download", headers=viewer_headers).status_code == 403
    assert client.get(f"{BASE}/artifacts/{artifact_id}/pages/1/preview", headers=viewer_headers).status_code == 403
    exploded = client.post(f"{BASE}/artifacts/{artifact_id}/visual-pages", headers=auth_headers,
                           json={"role": "EXPLODED_SCHEME", "page_numbers": [1]})
    assert exploded.status_code == 201, exploded.text
    spare = client.post(f"{BASE}/artifacts/{artifact_id}/visual-pages", headers=auth_headers,
                        json={"role": "SPARE_PARTS_LIST", "page_numbers": [2, 3]})
    assert spare.status_code == 201, spare.text
    same_page = client.post(f"{BASE}/artifacts/{artifact_id}/visual-pages", headers=auth_headers,
                            json={"role": "SPARE_PARTS_LIST", "page_numbers": [1]})
    assert same_page.status_code == 201
    assert len(client.get(f"{BASE}/artifacts/{artifact_id}/visual-pages", headers=auth_headers).json()) == 4
    assert client.post(f"{BASE}/artifacts/{artifact_id}/visual-pages", headers=auth_headers,
                       json={"role": "SPARE_PARTS_LIST", "page_numbers": [1, 4]}).status_code == 422
    assert client.post(f"{BASE}/artifacts/{artifact_id}/visual-pages", headers=auth_headers,
                       json={"role": "BOM", "page_numbers": [1]}).json()["detail"]["code"] == "catalog_visual_role_invalid"
    assert client.post(f"{BASE}/artifacts/{artifact_id}/visual-pages", headers=auth_headers,
                       json={"role": "EXPLODED_SCHEME", "page_numbers": [1]}).status_code == 409
    assert client.delete(f"{BASE}/visual-pages/{spare.json()[0]['id']}", headers=auth_headers).status_code == 204
    with session_factory() as db:
        owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        result = preview(db, owner, ResourceType.CATALOG_DEFINITION, catalog_id)
        assert result["can_delete"]
        counts = {item["code"]: item["count"] for item in result["owned_records_to_delete"]}
        assert counts["catalog_revision_assemblies"] == 1
        assert counts["catalog_revision_artifacts"] == 1
        assert counts["catalog_revision_visual_pages"] == 3
        assert db.scalar(select(func.count(PartCatalog.id)).where(PartCatalog.source_version == "PARTS_CATALOG_V2")) == 611
        assert db.scalar(select(func.count(RepairKit.id))) == 7
        assert (db.scalar(select(func.count(CatalogVisualSource.id))),
                db.scalar(select(func.count(CatalogVisualPartMap.id)))) == live_before
    assert client.delete(f"{BASE}/artifacts/{artifact_id}", headers=auth_headers).status_code == 204
    with session_factory() as db:
        assert db.get(CatalogRevisionArtifact, artifact_id) is None
        assert db.scalar(select(CatalogRevisionVisualPage.id).where(CatalogRevisionVisualPage.artifact_id == artifact_id)) is None
    second_id = _upload(client, auth_headers, assembly_id, _pdf(2)).json()["id"]
    assert client.post(f"{BASE}/artifacts/{second_id}/visual-pages", headers=auth_headers,
                       json={"role": "EXPLODED_SCHEME", "page_numbers": [1]}).status_code == 201
    assert client.delete(f"{BASE}/assemblies/{assembly_id}", headers=auth_headers).status_code == 204
    with session_factory() as db:
        assert db.get(CatalogRevisionAssembly, assembly_id) is None
        assert db.get(CatalogRevisionArtifact, second_id) is None
        assert db.scalar(select(CatalogRevisionVisualPage.id).where(CatalogRevisionVisualPage.artifact_id == second_id)) is None
        assert db.get(CatalogRevision, revision_id) is not None
        events = db.scalars(select(AuditLog).where(AuditLog.entity_type.in_(
            ["catalog_revision_assembly", "catalog_revision_artifact"]))).all()
        assert {event.action for event in events} >= {
            "ASSEMBLY_CREATED", "ASSEMBLY_UPDATED", "ASSEMBLY_DELETED",
            "CATALOG_SOURCE_UPLOADED", "CATALOG_SOURCE_DELETED",
            "VISUAL_PAGE_ROLE_ASSIGNED", "VISUAL_PAGE_ROLE_REMOVED",
        }
        deleted = next(event for event in events if event.action == "ASSEMBLY_DELETED")
        assert json.loads(deleted.details)["artifacts"][0]["artifact_id"] == second_id


def test_pdf_validation_and_draft_guards(client, auth_headers, session_factory, monkeypatch):
    catalog_id, revision_id = _workspace(client, auth_headers, session_factory)
    assembly_id = _assembly(client, auth_headers, revision_id).json()["id"]
    assert _upload(client, auth_headers, assembly_id, b"not a pdf").json()["detail"]["code"] == "catalog_source_invalid_pdf"
    assert _upload(client, auth_headers, assembly_id, b"%PDF-broken").status_code == 422
    assert _upload(client, auth_headers, assembly_id, _pdf(), media_type="image/png").status_code == 422
    from app.settings import settings
    with monkeypatch.context() as limits:
        limits.setattr(settings, "catalog_pdf_max_bytes", 12 * 1024 * 1024)
        too_large = _upload(client, auth_headers, assembly_id, b"%PDF-" + b"x" * (12 * 1024 * 1024))
    assert too_large.json()["detail"]["code"] == "catalog_source_too_large"
    artifact_id = _upload(client, auth_headers, assembly_id, _pdf(1)).json()["id"]
    assignment_id = client.post(f"{BASE}/artifacts/{artifact_id}/visual-pages", headers=auth_headers,
                                json={"role": "EXPLODED_SCHEME", "page_numbers": [1]}).json()[0]["id"]
    with session_factory() as db:
        db.get(CatalogRevision, revision_id).status = "PUBLISHED"
        db.commit()
        owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        result = preview(db, owner, ResourceType.CATALOG_DEFINITION, catalog_id)
        assert not result["can_delete"]
        assert any(item["code"] == "catalog_revisions" for item in result["blockers"])
    assert _assembly(client, auth_headers, revision_id).json()["detail"]["code"] == "catalog_revision_not_draft"
    assert _upload(client, auth_headers, assembly_id, _pdf()).json()["detail"]["code"] == "catalog_revision_not_draft"
    assert client.patch(f"{BASE}/assemblies/{assembly_id}", headers=auth_headers,
                        json={"name_en": "Changed"}).status_code == 409
    assert client.delete(f"{BASE}/assemblies/{assembly_id}", headers=auth_headers).status_code == 409
    assert client.delete(f"{BASE}/artifacts/{artifact_id}", headers=auth_headers).status_code == 409
    assert client.post(f"{BASE}/artifacts/{artifact_id}/visual-pages", headers=auth_headers,
                       json={"role": "SPARE_PARTS_LIST", "page_numbers": [1]}).status_code == 409
    assert client.delete(f"{BASE}/visual-pages/{assignment_id}", headers=auth_headers).status_code == 409
    assert client.get(f"{BASE}/artifacts/{artifact_id}/pages/1/preview", headers=auth_headers).status_code == 200
    with session_factory() as db:
        db.get(CatalogRevision, revision_id).status = "DRAFT"
        db.get(CatalogDefinition, catalog_id).is_active = False
        db.commit()
    assert _assembly(client, auth_headers, revision_id).json()["detail"]["code"] == "catalog_inactive"
