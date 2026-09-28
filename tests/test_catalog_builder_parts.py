"""01C draft parts, exact source pages, and preview/confirm isolation."""

import base64
import hashlib
import io
import os

import pytest
from app.catalog_admin.schemas import ArtifactUpload
from app.catalog_admin.visual_sources import upload_artifact
from app.governance.owner_data_deletion import ResourceType
from app.governance.owner_data_deletion import preview as owner_preview
from app.models import (
    AssetCategory,
    CatalogDefinition,
    CatalogRevision,
    CatalogRevisionArtifact,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
    CatalogVisualPartMap,
    PartCatalog,
    RepairKit,
    User,
)
from fastapi import HTTPException
from reportlab.pdfgen import canvas
from sqlalchemy import func, select

BASE = "/api/admin/catalog-builder"


def workspace(client, headers, factory):
    with factory() as db:
        category = AssetCategory(code="QA_PARTS_CATEGORY", name_bg="QA", name_en="QA", name_ru="QA",
                                 capabilities=["HAS_PARTS_CATALOG"])
        db.add(category)
        db.commit()
        category_id = category.id
    catalog = client.post(f"{BASE}/catalogs", headers=headers, json={
        "code": "QA_PARTS_CATALOG", "asset_category_id": category_id,
        "name_bg": "QA", "name_en": "QA", "name_ru": "QA",
    }).json()
    revision = client.post(f"{BASE}/catalogs/{catalog['id']}/revisions", headers=headers,
                           json={"revision_code": "A"}).json()
    def assembly(code):
        response = client.post(f"{BASE}/revisions/{revision['id']}/assemblies", headers=headers, json={
            "code": code, "name_bg": code, "name_en": code, "name_ru": code,
        })
        assert response.status_code == 201, response.text
        return response.json()["id"]
    return catalog["id"], revision["id"], assembly("PUMP"), assembly("VALVE")


def source(client, headers, assembly_id, marker="QA"):
    stream = io.BytesIO()
    document = canvas.Canvas(stream)
    for number in range(2):
        document.drawString(50, 700, f"{marker} {number}")
        document.showPage()
    document.save()
    content = stream.getvalue()
    artifact = client.post(f"{BASE}/assemblies/{assembly_id}/artifacts", headers=headers, json={
        "title": "QA source", "filename": "qa.pdf", "media_type": "application/pdf",
        "content_base64": base64.b64encode(content).decode(),
    })
    assert artifact.status_code == 201, artifact.text
    artifact_id = artifact.json()["id"]
    spare = client.post(f"{BASE}/artifacts/{artifact_id}/visual-pages", headers=headers,
                        json={"role": "SPARE_PARTS_LIST", "page_numbers": [1]})
    scheme = client.post(f"{BASE}/artifacts/{artifact_id}/visual-pages", headers=headers,
                         json={"role": "EXPLODED_SCHEME", "page_numbers": [2]})
    assert spare.status_code == 201 and scheme.status_code == 201
    return artifact_id, spare.json()[0]["id"], scheme.json()[0]["id"], hashlib.sha256(content).hexdigest()


def part(client, headers, assembly_id, position="12", number="A"):
    return client.post(f"{BASE}/assemblies/{assembly_id}/parts", headers=headers,
                       json={"position": position, "part_number": number, "name_en": "Test part"})


def csv_preview(client, headers, assembly_id, csv_text):
    return client.post(f"{BASE}/assemblies/{assembly_id}/parts/import-preview", headers=headers, json={
        "filename": "parts.csv", "content_base64": base64.b64encode(csv_text).decode(),
    })


def test_manual_parts_exact_pages_and_isolation(client, auth_headers, viewer_headers, session_factory):
    with session_factory() as db:
        live = tuple(db.scalar(select(func.count(model.id))) for model in
                     (PartCatalog, RepairKit, CatalogVisualPartMap))
    catalog_id, _, pump, valve = workspace(client, auth_headers, session_factory)
    artifact_id, spare, scheme, _ = source(client, auth_headers, pump)
    _, other_spare, _, _ = source(client, auth_headers, valve)
    assert part(client, auth_headers, pump, position=" ").status_code == 422
    assert part(client, auth_headers, pump, number=" ").status_code == 422
    missing_name = client.post(f"{BASE}/assemblies/{pump}/parts", headers=auth_headers,
                               json={"position": "1", "part_number": "N"})
    assert missing_name.status_code == 422
    first = part(client, auth_headers, pump)
    assert first.status_code == 201, first.text
    part_id = first.json()["id"]
    assert first.json()["validation_status"] == "INCOMPLETE"
    assert part(client, auth_headers, pump).status_code == 409
    assert part(client, auth_headers, pump, number="B").status_code == 201
    assert client.post(f"{BASE}/parts/{part_id}/source-pages", headers=auth_headers,
                       json={"visual_page_ids": [scheme]}).status_code == 422
    assert client.post(f"{BASE}/parts/{part_id}/source-pages", headers=auth_headers,
                       json={"visual_page_ids": [other_spare]}).status_code == 422
    assert client.post(f"{BASE}/parts/{part_id}/source-pages", headers=auth_headers,
                       json={"visual_page_ids": [spare, other_spare]}).status_code == 422
    assert client.get(f"{BASE}/assemblies/{pump}/spare-list-pages", headers=auth_headers).json()[0]["visual_page_id"] == spare
    mapped = client.post(f"{BASE}/parts/{part_id}/source-pages", headers=auth_headers,
                         json={"visual_page_ids": [spare]})
    assert mapped.status_code == 201, mapped.text
    assert client.get(f"{BASE}/parts/{part_id}", headers=auth_headers).json()["validation_status"] == "READY"
    assert client.post(f"{BASE}/parts/{part_id}/source-pages", headers=auth_headers,
                       json={"visual_page_ids": [spare]}).status_code == 409
    assert client.patch(f"{BASE}/parts/{part_id}", headers=auth_headers,
                        json={"name_bg": "  Тест  ", "quantity_raw": " AR "}).json()["name_bg"] == "Тест"
    assert client.get(f"{BASE}/assemblies/{pump}/parts", headers=viewer_headers).status_code == 403
    assert client.delete(f"{BASE}/part-page-maps/{mapped.json()[0]['id']}", headers=auth_headers).status_code == 204
    assert client.delete(f"{BASE}/parts/{part_id}", headers=auth_headers).status_code == 204
    assert client.patch(f"{BASE}/catalogs/{catalog_id}", headers=auth_headers,
                        json={"is_active": False}).status_code == 200
    assert part(client, auth_headers, pump, number="C").status_code == 409
    with session_factory() as db:
        assert live == tuple(db.scalar(select(func.count(model.id))) for model in
                             (PartCatalog, RepairKit, CatalogVisualPartMap))
        assert db.scalar(select(func.count(CatalogRevisionPartPageMap.id))) == 0
    assert artifact_id


def test_csv_preview_confirm_and_ambiguity(client, auth_headers, session_factory):
    _, _, pump, _ = workspace(client, auth_headers, session_factory)
    _, spare, _, sha = source(client, auth_headers, pump)
    second_artifact, second_spare, _, second_sha = source(client, auth_headers, pump, "SECOND")
    with session_factory() as db:
        before = db.scalar(select(func.count(CatalogRevisionPart.id)))
    ambiguous = csv_preview(client, auth_headers, pump,
                            b"position,part_number,name_en,source_page\n1,A,Seal,1\n")
    assert ambiguous.json()["summary"]["error_rows"] == 1
    csv_data = (f"position,part_number,name_en,quantity_raw,source_page,source_artifact_sha256\n"
                f"1,A,Seal,AR,1,{sha}\n").encode()
    preview = csv_preview(client, auth_headers, pump, csv_data)
    assert preview.status_code == 200, preview.text
    assert preview.json()["summary"]["valid_rows"] == 1
    with session_factory() as db:
        assert db.scalar(select(func.count(CatalogRevisionPart.id))) == before
    confirmed = client.post(f"{BASE}/assemblies/{pump}/parts/import-confirm", headers=auth_headers,
                            json={"token": preview.json()["token"]})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["created_count"] == 1
    created_id = confirmed.json()["part_ids"][0]
    second_mapping = client.post(f"{BASE}/parts/{created_id}/source-pages", headers=auth_headers,
                                 json={"visual_page_ids": [second_spare]})
    assert second_mapping.status_code == 201
    assert len(second_mapping.json()) == 2
    assert client.delete(f"{BASE}/artifacts/{second_artifact}", headers=auth_headers).status_code == 204
    assert [item["visual_page_id"] for item in client.get(f"{BASE}/parts/{created_id}/source-pages",
                                                         headers=auth_headers).json()] == [spare]
    assert client.post(f"{BASE}/assemblies/{pump}/parts/import-confirm", headers=auth_headers,
                       json={"token": preview.json()["token"]}).status_code == 409
    assert csv_preview(client, auth_headers, pump, csv_data).json()["summary"]["error_rows"] == 1
    duplicate = csv_preview(client, auth_headers, pump,
                            b"position,part_number,name_en\n2,B,Seal\n2,B,Valve\n")
    assert duplicate.json()["summary"]["duplicate_rows"] == 1
    warning = csv_preview(client, auth_headers, pump, b"position,part_number,name_en\n3,C,Ring\n")
    assert warning.json()["summary"]["warning_rows"] == 1
    assert client.post(f"{BASE}/assemblies/{pump}/parts/import-confirm", headers=auth_headers,
                       json={"token": warning.json()["token"]}).status_code == 422
    assert client.post(f"{BASE}/assemblies/{pump}/parts/import-confirm", headers=auth_headers,
                       json={"token": warning.json()["token"], "confirm_warnings": True}).status_code == 200
    numeric = csv_preview(client, auth_headers, pump,
                          b"position,part_number,name_en,quantity,quantity_raw\n5,E,Seal,2,2 pcs\n")
    assert numeric.status_code == 200
    assert numeric.json()["summary"]["warning_rows"] == 1
    assert numeric.json()["rows"][0]["normalized"]["quantity_raw"] == "2 pcs"
    negative = csv_preview(client, auth_headers, pump,
                           b"position,part_number,name_en,quantity\n6,F,Seal,-1\n")
    assert negative.json()["summary"]["error_rows"] == 1
    assert csv_preview(client, auth_headers, pump, b"\xff").status_code == 422
    huge_page = csv_preview(client, auth_headers, pump,
                            b"position,part_number,name_en,source_page\n4,D,Ring," + b"9" * 5000 + b"\n")
    assert huge_page.status_code == 200
    assert huge_page.json()["summary"]["error_rows"] == 1
    assert csv_preview(client, auth_headers, pump, b"position,part_number,name_en\n" + b"x" * 600_000).status_code == 422
    too_many = b"position,part_number,name_en\n" + b"1,Z,Ring\n" * 1001
    assert csv_preview(client, auth_headers, pump, too_many).status_code == 422
    assert spare and sha and second_sha


def test_nondraft_blocks_mutation_and_owner_preview_lists_parts(client, auth_headers, session_factory):
    catalog_id, revision_id, pump, _ = workspace(client, auth_headers, session_factory)
    _, spare, _, _ = source(client, auth_headers, pump)
    created = part(client, auth_headers, pump)
    assert created.status_code == 201
    assert client.post(f"{BASE}/parts/{created.json()['id']}/source-pages", headers=auth_headers,
                       json={"visual_page_ids": [spare]}).status_code == 201
    with session_factory() as db:
        owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        report = owner_preview(db, owner, ResourceType.CATALOG_DEFINITION, catalog_id)
        codes = {item["code"]: item["count"] for item in report["owned_records_to_delete"]}
        assert codes["catalog_revision_parts"] == 1
        assert codes["catalog_revision_part_page_maps"] == 1
        revision = db.get(CatalogRevision, revision_id)
        revision.status = "PUBLISHED"
        db.commit()
    assert part(client, auth_headers, pump, number="NEXT").status_code == 409
    assert client.delete(f"{BASE}/parts/{created.json()['id']}", headers=auth_headers).status_code == 409
    assert client.get(f"{BASE}/parts/{created.json()['id']}", headers=auth_headers).status_code == 200
    with session_factory() as db:
        owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        report = owner_preview(db, owner, ResourceType.CATALOG_DEFINITION, catalog_id)
        assert report["can_delete"] is False


def test_owner_deletes_draft_parts_and_page_maps(client, auth_headers, session_factory):
    catalog_id, _, pump, _ = workspace(client, auth_headers, session_factory)
    _, spare, _, _ = source(client, auth_headers, pump)
    created = part(client, auth_headers, pump)
    assert created.status_code == 201
    assert client.post(f"{BASE}/parts/{created.json()['id']}/source-pages", headers=auth_headers,
                       json={"visual_page_ids": [spare]}).status_code == 201
    path = f"/api/owner/data-deletion/catalog_definition/{catalog_id}"
    preview_response = client.get(f"{path}/preview", headers=auth_headers)
    assert preview_response.status_code == 200, preview_response.text
    report = preview_response.json()
    assert report["can_delete"]
    owned = {item["code"]: item["count"] for item in report["owned_records_to_delete"]}
    assert owned["catalog_revision_parts"] == 1
    assert owned["catalog_revision_part_page_maps"] == 1
    deleted = client.post(f"{path}/execute", headers=auth_headers, json={
        "current_password": os.environ["ADMIN_PASSWORD"],
        "confirmation_text": report["confirmation_text"],
    })
    assert deleted.status_code == 200, deleted.text
    with session_factory() as db:
        assert db.get(CatalogDefinition, catalog_id) is None
        assert db.scalar(select(func.count(CatalogRevisionPart.id))) == 0
        assert db.scalar(select(func.count(CatalogRevisionPartPageMap.id))) == 0


def test_duplicate_pdf_integrity_fallback_returns_existing_id(
    client, auth_headers, session_factory, monkeypatch,
):
    _, _, pump, _ = workspace(client, auth_headers, session_factory)
    artifact_id, _, _, _ = source(client, auth_headers, pump)
    with session_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        content = db.get(CatalogRevisionArtifact, artifact_id).content
        original_scalar = db.scalar
        hidden = False

        def hide_first_duplicate(statement, *args, **kwargs):
            nonlocal hidden
            result = original_scalar(statement, *args, **kwargs)
            if isinstance(result, CatalogRevisionArtifact) and not hidden:
                hidden = True
                return None
            return result

        monkeypatch.setattr(db, "scalar", hide_first_duplicate)
        with pytest.raises(HTTPException) as error:
            upload_artifact(db, actor, pump, ArtifactUpload(
                title="QA", filename="qa.pdf", media_type="application/pdf",
                content_base64=base64.b64encode(content).decode(),
            ))
        assert error.value.status_code == 409
        assert error.value.detail == {"code": "catalog_source_duplicate", "artifact_id": artifact_id}
