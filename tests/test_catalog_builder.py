"""Disposable Builder records; verified V2 catalog and seed inventory are read-only anchors."""

import base64
import io
import os

import pytest
from app.authorization_inventory import build_authorization_inventory
from app.governance.owner_data_deletion import ResourceType, preview
from app.main import app
from app.models import (
    AssetCategory,
    CatalogAssetBinding,
    CatalogDefinition,
    CatalogRevision,
    Machine,
    PartCatalog,
    User,
)
from app.security import create_access_token
from fastapi import HTTPException
from reportlab.pdfgen import canvas
from sqlalchemy import func, select

BASE = "/api/admin/catalog-builder"


@pytest.mark.parametrize("role", ["director", "mechanic", "observer"])
def test_builder_requires_parts_manage(client, session_factory, role):
    with session_factory() as db:
        actor = User(email=f"qa-builder-{role}@invalid.example", full_name="QA Builder",
                     password_hash="unused-test-hash", role=role, profile_status="PROFILE_COMPLETE")
        db.add(actor)
        db.commit()
        headers = {"Authorization": f"Bearer {create_access_token(actor)}"}
    assert client.get(f"{BASE}/catalogs", headers=headers).status_code == 403
    assert _create(client, headers, "QA_FORBIDDEN", 1).status_code == 403
    assert client.post(f"{BASE}/catalogs/1/revisions", headers=headers,
                       json={"revision_code": "A"}).status_code == 403
    assert client.post(f"{BASE}/catalogs/1/assets/1", headers=headers).status_code == 403
    assert client.post(f"{BASE}/visual-pages/1/hotspots", headers=headers,
                       json={"position": "1", "x": .1, "y": .1, "width": .1, "height": .1}).status_code == 403
    assert client.patch(f"{BASE}/hotspots/1", headers=headers,
                        json={"expected_version": 1, "x": .2}).status_code == 403
    assert client.post(f"{BASE}/hotspots/1/verify", headers=headers,
                       json={"expected_version": 1}).status_code == 403
    assert client.post(f"{BASE}/hotspots/1/unverify", headers=headers,
                       json={"expected_version": 1}).status_code == 403
    assert client.delete(f"{BASE}/hotspots/1?expected_version=1", headers=headers).status_code == 403
    assert client.post(f"{BASE}/assemblies/1/repair-kits", headers=headers,
                       json={"code": "QA", "name_en": "QA"}).status_code == 403
    assert client.patch(f"{BASE}/repair-kits/1", headers=headers,
                        json={"expected_version": 1, "name_en": "QA"}).status_code == 403
    assert client.delete(f"{BASE}/repair-kits/1?expected_version=1", headers=headers).status_code == 403
    assert client.post(f"{BASE}/repair-kits/1/components", headers=headers,
                       json={"part_id": 1, "quantity": 1}).status_code == 403
    assert client.patch(f"{BASE}/repair-kit-components/1", headers=headers,
                        json={"expected_version": 1, "quantity": 2}).status_code == 403
    assert client.delete(f"{BASE}/repair-kit-components/1?expected_version=1", headers=headers).status_code == 403
    assert client.get(f"{BASE}/revisions/1/publication-readiness", headers=headers).status_code == 403
    assert client.post(f"{BASE}/revisions/1/publish", headers=headers, json={}).status_code == 403
    assert client.post(f"{BASE}/revisions/1/clone", headers=headers, json={}).status_code == 403


def test_builder_routes_are_permission_classified():
    report = build_authorization_inventory(app)
    assert report.valid, report.errors
    builder = [route for route in report.routes if route.path.startswith(BASE)]
    assert len(builder) == 78
    assert all(route.permission == "parts.manage" for route in builder)


def _category(factory, code: str, supported: bool = True):
    with factory() as db:
        item = AssetCategory(code=code, name_bg=code, name_en=code, name_ru=code,
                             capabilities=["HAS_PARTS_CATALOG"] if supported else [])
        db.add(item)
        db.commit()
        return item.id


def _machine(factory, category_id: int, inventory: str, brand: str):
    with factory() as db:
        category = db.get(AssetCategory, category_id)
        item = Machine(inventory_number=inventory, name=inventory, category=category.code,
                       category_id=category_id, brand=brand, model=f"{brand}-QA")
        db.add(item)
        db.commit()
        return item.id


def _create(client, headers, code, category_id):
    return client.post(f"{BASE}/catalogs", headers=headers, json={
        "code": code, "asset_category_id": category_id,
        "name_bg": code, "name_en": code, "name_ru": code,
    })


def test_generic_builder_bindings_and_lifecycle(client, auth_headers, session_factory):
    category_a = _category(session_factory, "QA_BUILDER_A")
    category_b = _category(session_factory, "QA_BUILDER_B")
    category_without = _category(session_factory, "QA_BUILDER_NONE", False)
    machine_a = _machine(session_factory, category_a, "QA_BUILDER_A1", "Brand One")
    machine_a2 = _machine(session_factory, category_a, "QA_BUILDER_A2", "Other Brand")
    machine_b = _machine(session_factory, category_b, "QA_BUILDER_B1", "Brand One")
    assert _create(client, auth_headers, "QA_NOT_SUPPORTED", category_without).json()["detail"]["code"] == "catalog_category_not_supported"
    created = _create(client, auth_headers, "QA_CATALOG_A", category_a)
    assert created.status_code == 201, created.text
    catalog_id = created.json()["id"]
    second = _create(client, auth_headers, "QA_CATALOG_A2", category_a)
    assert second.status_code == 201
    second_id = second.json()["id"]
    assert _create(client, auth_headers, "QA_CATALOG_A", category_a).json()["detail"]["code"] == "catalog_code_duplicate"
    assert client.post(f"{BASE}/catalogs/{catalog_id}/assets/{machine_b}", headers=auth_headers).json()["detail"]["code"] == "catalog_asset_category_mismatch"
    assert client.post(f"{BASE}/catalogs/{catalog_id}/assets/{machine_a}", headers=auth_headers).status_code == 201
    assert client.post(f"{BASE}/catalogs/{catalog_id}/assets/{machine_a2}", headers=auth_headers).status_code == 201
    assert client.patch(f"/api/machines/{machine_a}", headers=auth_headers,
                        json={"category_id": category_b}).json()["detail"]["code"] == "catalog_asset_category_in_use"
    assert client.patch(f"/api/categories/{category_a}", headers=auth_headers,
                        json={"capabilities": []}).json()["detail"]["code"] == "category_capability_in_use"
    assert client.post(f"{BASE}/catalogs/{second_id}/assets/{machine_a}", headers=auth_headers).json()["detail"]["code"] == "catalog_asset_already_bound"
    assert len(client.get(f"{BASE}/catalogs/{catalog_id}/assets", headers=auth_headers).json()) == 2
    assert client.patch(f"{BASE}/catalogs/{catalog_id}", headers=auth_headers,
                        json={"asset_category_id": category_b}).json()["detail"]["code"] == "catalog_category_in_use"
    assert client.patch(f"{BASE}/catalogs/{catalog_id}", headers=auth_headers,
                        json={"code": "OTHER"}).json()["detail"]["code"] == "catalog_code_immutable"
    assert client.post(f"{BASE}/catalogs/{catalog_id}/revisions", headers=auth_headers,
                       json={"revision_code": "A", "status": "PUBLISHED"}).json()["detail"]["code"] == "catalog_revision_status_managed"
    revision = client.post(f"{BASE}/catalogs/{catalog_id}/revisions", headers=auth_headers,
                           json={"revision_code": "A", "change_note": "QA"})
    assert revision.status_code == 201 and revision.json()["status"] == "DRAFT"
    revision_id = revision.json()["id"]
    assert client.post(f"{BASE}/catalogs/{catalog_id}/revisions", headers=auth_headers,
                       json={"revision_code": "A"}).json()["detail"]["code"] == "catalog_revision_duplicate"
    assert client.patch(f"{BASE}/revisions/{revision_id}", headers=auth_headers,
                        json={"change_note": "Updated QA"}).json()["change_note"] == "Updated QA"
    assert client.patch(f"{BASE}/revisions/{revision_id}", headers=auth_headers,
                        json={"status": "PUBLISHED"}).json()["detail"]["code"] == "catalog_revision_status_managed"
    assert client.patch(f"{BASE}/revisions/{revision_id}", headers=auth_headers,
                        json={"revision_code": "B"}).json()["detail"]["code"] == "catalog_revision_code_immutable"
    assert client.patch(f"{BASE}/catalogs/{catalog_id}", headers=auth_headers,
                        json={"is_active": False}).status_code == 200
    assert len(client.get(f"{BASE}/catalogs/{catalog_id}/assets", headers=auth_headers).json()) == 2
    assert len(client.get(f"{BASE}/catalogs/{catalog_id}/revisions", headers=auth_headers).json()) == 1
    assert client.post(f"{BASE}/catalogs/{catalog_id}/revisions", headers=auth_headers,
                       json={"revision_code": "B"}).json()["detail"]["code"] == "catalog_inactive"
    assert client.post(f"{BASE}/catalogs/{catalog_id}/assets/{machine_b}", headers=auth_headers).json()["detail"]["code"] == "catalog_inactive"
    assert client.patch(f"{BASE}/catalogs/{catalog_id}", headers=auth_headers,
                        json={"is_active": True}).status_code == 200
    assert client.post(f"{BASE}/catalogs/{catalog_id}/revisions", headers=auth_headers,
                       json={"revision_code": "B"}).status_code == 201
    assert any(route.path == f"{BASE}/revisions/{{revision_id}}/publish" for route in client.app.routes)
    with session_factory() as db:
        assert db.scalar(select(func.count(PartCatalog.id)).where(PartCatalog.source_version == "PARTS_CATALOG_V2")) == 611


def test_eligible_assets_and_owner_preview(client, auth_headers, session_factory):
    category_id = _category(session_factory, "QA_BUILDER_OWNER")
    machine_id = _machine(session_factory, category_id, "QA_BUILDER_OWNED", "Any Brand")
    catalog_id = _create(client, auth_headers, "QA_OWNER_CATALOG", category_id).json()["id"]
    assert [item["id"] for item in client.get(f"{BASE}/catalogs/{catalog_id}/eligible-assets", headers=auth_headers).json()] == [machine_id]
    assert [item["id"] for item in client.get(f"{BASE}/catalogs/{catalog_id}/eligible-assets",
                                                   headers=auth_headers, params={"search": "Any Brand"}).json()] == [machine_id]
    assert client.post(f"{BASE}/catalogs/{catalog_id}/assets/{machine_id}", headers=auth_headers).status_code == 201
    assert client.post(f"{BASE}/catalogs/{catalog_id}/revisions", headers=auth_headers,
                       json={"revision_code": "A"}).status_code == 201
    with session_factory() as db:
        owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        result = preview(db, owner, ResourceType.CATALOG_DEFINITION, catalog_id)
        assert result["can_delete"]
        assert {(item["code"], item["count"]) for item in result["owned_records_to_delete"]} == {
            ("catalog_revisions", 1), ("catalog_asset_bindings", 1),
        }
        ordinary = User(id=owner.id + 1000, role="administrator", is_system_owner=False)
        try:
            preview(db, ordinary, ResourceType.CATALOG_DEFINITION, catalog_id)
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("ordinary administrator reached owner deletion")
    assert client.delete(f"{BASE}/catalogs/{catalog_id}/assets/{machine_id}", headers=auth_headers).status_code == 204
    with session_factory() as db:
        assert db.scalar(select(CatalogAssetBinding.id).where(CatalogAssetBinding.machine_id == machine_id)) is None
        assert db.get(CatalogDefinition, catalog_id) is not None
        assert db.scalar(select(CatalogRevision.id).where(CatalogRevision.catalog_id == catalog_id)) is not None


def test_owner_deletes_only_builder_children(client, auth_headers, session_factory):
    category_id = _category(session_factory, "QA_BUILDER_DELETE")
    machine_id = _machine(session_factory, category_id, "QA_BUILDER_DELETE_ASSET", "QA")
    catalog_id = _create(client, auth_headers, "QA_DELETE_CATALOG", category_id).json()["id"]
    client.post(f"{BASE}/catalogs/{catalog_id}/assets/{machine_id}", headers=auth_headers)
    revision_id = client.post(f"{BASE}/catalogs/{catalog_id}/revisions", headers=auth_headers,
                              json={"revision_code": "A"}).json()["id"]
    assembly_id = client.post(f"{BASE}/revisions/{revision_id}/assemblies", headers=auth_headers,
                              json={"code": "PUMP", "name_bg": "QA", "name_en": "QA",
                                    "name_ru": "QA"}).json()["id"]
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.drawString(40, 700, "QA")
    pdf.showPage()
    pdf.save()
    artifact_id = client.post(f"{BASE}/assemblies/{assembly_id}/artifacts", headers=auth_headers,
                              json={"title": "QA", "filename": "qa.pdf", "media_type": "application/pdf",
                                    "content_base64": base64.b64encode(stream.getvalue()).decode()}).json()["id"]
    assert client.post(f"{BASE}/artifacts/{artifact_id}/visual-pages", headers=auth_headers,
                       json={"role": "EXPLODED_SCHEME", "page_numbers": [1]}).status_code == 201
    before = client.get(f"/api/owner/data-deletion/catalog_definition/{catalog_id}/preview",
                        headers=auth_headers)
    assert before.status_code == 200 and before.json()["can_delete"]
    assert {item["code"] for item in before.json()["owned_records_to_delete"]} >= {
        "catalog_revision_assemblies", "catalog_revision_artifacts", "catalog_revision_visual_pages"}
    with session_factory() as db:
        controlled_count = db.scalar(select(func.count(PartCatalog.id)).where(
            PartCatalog.source_version == "PARTS_CATALOG_V2"))
    result = client.post(f"/api/owner/data-deletion/catalog_definition/{catalog_id}/execute",
                         headers=auth_headers, json={
                             "current_password": os.environ["ADMIN_PASSWORD"],
                             "confirmation_text": before.json()["confirmation_text"],
                         })
    assert result.status_code == 200, result.text
    with session_factory() as db:
        assert db.get(CatalogDefinition, catalog_id) is None
        assert db.scalar(select(CatalogAssetBinding.id).where(CatalogAssetBinding.catalog_id == catalog_id)) is None
        assert db.scalar(select(CatalogRevision.id).where(CatalogRevision.catalog_id == catalog_id)) is None
        assert db.get(Machine, machine_id) is not None
        assert db.scalar(select(func.count(PartCatalog.id)).where(
            PartCatalog.source_version == "PARTS_CATALOG_V2")) == controlled_count
