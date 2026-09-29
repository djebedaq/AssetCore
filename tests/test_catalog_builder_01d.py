"""01D draft mapping and kit invariants through the permissioned Builder API."""

import os

import pytest
from app.governance.owner_data_deletion import ResourceType
from app.governance.owner_data_deletion import preview as owner_preview
from app.models import (
    CatalogDefinition,
    CatalogPositionHotspot,
    CatalogRevision,
    CatalogRevisionPositionHotspot,
    CatalogRevisionRepairKit,
    CatalogRevisionRepairKitComponent,
    PartCatalog,
    RepairKit,
    User,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from test_catalog_builder_parts import BASE, part, source, workspace


def _hotspot(client, headers, page_id, position="12", **geometry):
    return client.post(f"{BASE}/visual-pages/{page_id}/hotspots", headers=headers,
                       json={"position": position, "x": 0.2, "y": 0.3,
                             "width": 0.1, "height": 0.1, **geometry})


def _kit(client, headers, assembly_id, **values):
    return client.post(f"{BASE}/assemblies/{assembly_id}/repair-kits", headers=headers,
                       json={"code": "KIT_SEALS", "name_bg": "Уплътнения", **values})


def test_position_hotspots_geometry_verification_and_variants(client, auth_headers, session_factory):
    _, _, pump, valve = workspace(client, auth_headers, session_factory)
    artifact, spare, scheme, sha = source(client, auth_headers, pump)
    source(client, auth_headers, valve)
    assert part(client, auth_headers, pump, position="12", number="A").status_code == 201
    assert part(client, auth_headers, pump, position="12", number="B").status_code == 201
    assert part(client, auth_headers, valve, position="99", number="X").status_code == 201
    long_position = "P" * 80
    assert part(client, auth_headers, pump, position=long_position, number="LONG").status_code == 201

    pages = client.get(f"{BASE}/assemblies/{pump}/exploded-pages", headers=auth_headers).json()
    assert len(pages) == 1
    assert pages[0]["visual_page_id"] == scheme and pages[0]["sha256"] == sha
    assert pages[0]["hotspot_count"] == pages[0]["verified_hotspot_count"] == 0
    assert client.get(f"{BASE}/visual-pages/{spare}/hotspots", headers=auth_headers).status_code == 404
    assert _hotspot(client, auth_headers, spare).status_code == 404
    assert _hotspot(client, auth_headers, scheme, position="99").status_code == 422
    assert _hotspot(client, auth_headers, scheme, position="unknown").status_code == 422
    for geometry in ({"x": -0.1}, {"y": 1.1}, {"width": 0.001}, {"height": 0},
                     {"x": 0.95, "width": 0.1}, {"y": 0.95, "height": 0.1}):
        assert _hotspot(client, auth_headers, scheme, **geometry).status_code == 422
    for value in ("NaN", "Infinity", "-Infinity"):
        raw = '{"position":"12","x":' + value + ',"y":0.3,"width":0.1,"height":0.1}'
        assert client.post(f"{BASE}/visual-pages/{scheme}/hotspots", headers={**auth_headers,
                           "Content-Type": "application/json"}, content=raw).status_code == 422

    first = _hotspot(client, auth_headers, scheme)
    second = _hotspot(client, auth_headers, scheme)
    long_hotspot = _hotspot(client, auth_headers, scheme, position=long_position)
    assert first.status_code == second.status_code == long_hotspot.status_code == 201
    assert long_hotspot.json()["position"] == long_position
    rows = client.get(f"{BASE}/visual-pages/{scheme}/hotspots", headers=auth_headers).json()
    assert len(rows) == 3 and any(row["position"] == long_position for row in rows)
    assert rows[0]["provenance"] == "MANUAL_BUILDER" and not rows[0]["is_verified"]
    coverage = client.get(f"{BASE}/assemblies/{pump}/hotspot-coverage", headers=auth_headers).json()
    position = next(row for row in coverage if row["position"] == "12")
    assert position["part_count"] == 2 and position["part_numbers"] == ["A", "B"]
    assert position["hotspot_count"] == 2 and position["state"] == "UNVERIFIED"

    hotspot_id = first.json()["id"]
    verified = client.post(f"{BASE}/hotspots/{hotspot_id}/verify", headers=auth_headers,
                           json={"expected_version": first.json()["version"]})
    assert verified.status_code == 200 and verified.json()["is_verified"]
    stale = client.patch(f"{BASE}/hotspots/{hotspot_id}", headers=auth_headers,
                         json={"expected_version": first.json()["version"], "x": 0.4})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "catalog_hotspot_stale"
    edited = client.patch(f"{BASE}/hotspots/{hotspot_id}", headers=auth_headers,
                          json={"expected_version": verified.json()["version"], "x": 0.4})
    assert edited.status_code == 200 and not edited.json()["is_verified"]
    assert edited.json()["verified_by_id"] is None and edited.json()["verified_at"] is None
    assert client.delete(f"{BASE}/hotspots/{hotspot_id}?expected_version={first.json()['version']}",
                         headers=auth_headers).status_code == 409
    assert client.delete(f"{BASE}/hotspots/{hotspot_id}?expected_version={edited.json()['version']}",
                         headers=auth_headers).status_code == 204
    with session_factory() as db:
        assert db.scalar(select(func.count(CatalogRevisionPositionHotspot.id))) == 2


def test_part_position_and_kit_references_are_safe(client, auth_headers, session_factory):
    _, _, pump, valve = workspace(client, auth_headers, session_factory)
    artifact, spare, scheme, _ = source(client, auth_headers, pump)
    _, other_spare, _, _ = source(client, auth_headers, valve)
    first = part(client, auth_headers, pump, number="A").json()
    second = part(client, auth_headers, pump, number="B").json()
    other = part(client, auth_headers, valve, number="C").json()
    hotspot = _hotspot(client, auth_headers, scheme).json()
    assert client.patch(f"{BASE}/parts/{first['id']}", headers=auth_headers,
                        json={"position": "13"}).status_code == 200
    blocked = client.patch(f"{BASE}/parts/{second['id']}", headers=auth_headers,
                           json={"position": "14"})
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "catalog_part_position_in_use"
    assert client.delete(f"{BASE}/parts/{second['id']}", headers=auth_headers).status_code == 409

    invalid_source = _kit(client, auth_headers, pump, source_visual_page_id=scheme)
    assert invalid_source.status_code == 422
    assert _kit(client, auth_headers, pump, source_visual_page_id=other_spare).status_code == 422
    created = _kit(client, auth_headers, pump, source_visual_page_id=spare)
    assert created.status_code == 201, created.text
    kit = created.json()
    assert kit["validation_status"] == "INCOMPLETE"
    assert _kit(client, auth_headers, pump).status_code == 409
    cross = client.post(f"{BASE}/repair-kits/{kit['id']}/components", headers=auth_headers,
                        json={"part_id": other["id"], "quantity": 1})
    assert cross.status_code == 422 and cross.json()["detail"]["code"] == "catalog_repair_kit_cross_assembly"
    assert client.post(f"{BASE}/repair-kits/{kit['id']}/components", headers=auth_headers,
                       json={"part_id": first["id"], "quantity": 0}).status_code == 422
    added = client.post(f"{BASE}/repair-kits/{kit['id']}/components", headers=auth_headers,
                        json={"part_id": first["id"], "quantity": 2, "is_optional": True})
    assert added.status_code == 201, added.text
    component = added.json()
    assert component["part"]["position"] == "13" and component["is_optional"]
    assert client.post(f"{BASE}/repair-kits/{kit['id']}/components", headers=auth_headers,
                       json={"part_id": first["id"], "quantity": 1}).status_code == 409
    assert client.patch(f"{BASE}/repair-kits/{kit['id']}", headers=auth_headers,
                        json={"expected_version": 2, "code": "CHANGED"}).json()["detail"]["code"] == "catalog_repair_kit_code_immutable"
    assert client.delete(f"{BASE}/parts/{first['id']}", headers=auth_headers).json()["detail"]["code"] == "catalog_part_in_repair_kit"
    assert client.delete(f"{BASE}/visual-pages/{spare}", headers=auth_headers).json()["detail"]["code"] == "catalog_repair_kit_source_page_in_use"
    assert client.delete(f"{BASE}/artifacts/{artifact}", headers=auth_headers).json()["detail"]["code"] == "catalog_repair_kit_source_page_in_use"
    updated = client.patch(f"{BASE}/repair-kit-components/{component['id']}", headers=auth_headers,
                           json={"expected_version": component["version"], "quantity": 3, "note": "Confirmed"})
    assert updated.status_code == 200 and float(updated.json()["quantity"]) == 3
    assert client.delete(f"{BASE}/repair-kit-components/{component['id']}?expected_version={updated.json()['version']}",
                         headers=auth_headers).status_code == 204
    kit = client.get(f"{BASE}/repair-kits/{kit['id']}", headers=auth_headers).json()
    assert kit["component_count"] == 0
    assert kit["code_locked"] is True
    assert client.patch(f"{BASE}/repair-kits/{kit['id']}", headers=auth_headers,
                        json={"expected_version": kit["version"], "code": "CHANGED"}).json()["detail"]["code"] == "catalog_repair_kit_code_immutable"
    assert client.delete(f"{BASE}/repair-kits/{kit['id']}?expected_version={kit['version']}",
                         headers=auth_headers).status_code == 204
    assert client.delete(f"{BASE}/visual-pages/{spare}", headers=auth_headers).status_code == 204
    assert client.delete(f"{BASE}/hotspots/{hotspot['id']}?expected_version={hotspot['version']}",
                         headers=auth_headers).status_code == 204
    assert client.delete(f"{BASE}/parts/{second['id']}", headers=auth_headers).status_code == 204


def test_assembly_delete_isolated_from_live_catalog(client, auth_headers, session_factory):
    with session_factory() as db:
        before = tuple(db.scalar(select(func.count(model.id))) for model in
                       (PartCatalog, RepairKit, CatalogPositionHotspot))
    _, revision_id, pump, _ = workspace(client, auth_headers, session_factory)
    _, spare, scheme, _ = source(client, auth_headers, pump)
    item = part(client, auth_headers, pump).json()
    _hotspot(client, auth_headers, scheme)
    kit = _kit(client, auth_headers, pump, source_visual_page_id=spare).json()
    client.post(f"{BASE}/repair-kits/{kit['id']}/components", headers=auth_headers,
                json={"part_id": item["id"], "quantity": 1})
    assembly = client.get(f"{BASE}/revisions/{revision_id}/assemblies", headers=auth_headers)
    # The selected assembly projection reports the complete draft subtree.
    assert assembly.status_code == 200
    assert client.delete(f"{BASE}/assemblies/{pump}", headers=auth_headers).status_code == 204
    with session_factory() as db:
        assert db.scalar(select(func.count(CatalogRevisionPositionHotspot.id))) == 0
        assert db.scalar(select(func.count(CatalogRevisionRepairKit.id))) == 0
        after = tuple(db.scalar(select(func.count(model.id))) for model in
                      (PartCatalog, RepairKit, CatalogPositionHotspot))
    assert after == before


def test_page_artifact_cleanup_and_lifecycle_guards(client, auth_headers, session_factory):
    catalog_id, revision_id, pump, _ = workspace(client, auth_headers, session_factory)
    artifact_id, _, scheme, _ = source(client, auth_headers, pump)
    part(client, auth_headers, pump)
    _hotspot(client, auth_headers, scheme)
    assert client.delete(f"{BASE}/visual-pages/{scheme}", headers=auth_headers).status_code == 204
    with session_factory() as db:
        assert db.scalar(select(func.count(CatalogRevisionPositionHotspot.id))) == 0
    scheme = client.post(f"{BASE}/artifacts/{artifact_id}/visual-pages", headers=auth_headers,
                         json={"role": "EXPLODED_SCHEME", "page_numbers": [2]}).json()[0]["id"]
    hotspot = _hotspot(client, auth_headers, scheme).json()
    with session_factory() as db:
        db.get(CatalogDefinition, catalog_id).is_active = False
        db.commit()
    assert _hotspot(client, auth_headers, scheme).json()["detail"]["code"] == "catalog_inactive"
    assert _kit(client, auth_headers, pump).json()["detail"]["code"] == "catalog_inactive"
    with session_factory() as db:
        db.get(CatalogDefinition, catalog_id).is_active = True
        db.get(CatalogRevision, revision_id).status = "PUBLISHED"
        db.commit()
    assert client.post(f"{BASE}/hotspots/{hotspot['id']}/verify", headers=auth_headers,
                       json={"expected_version": 1}).json()["detail"]["code"] == "catalog_revision_not_draft"
    assert _kit(client, auth_headers, pump).json()["detail"]["code"] == "catalog_revision_not_draft"
    with session_factory() as db:
        db.get(CatalogRevision, revision_id).status = "DRAFT"
        db.commit()
    assert client.delete(f"{BASE}/artifacts/{artifact_id}", headers=auth_headers).status_code == 204
    with session_factory() as db:
        assert db.scalar(select(func.count(CatalogRevisionPositionHotspot.id))) == 0


def test_owner_preview_and_execution_include_all_01d_descendants(client, auth_headers, session_factory):
    catalog_id, _, pump, _ = workspace(client, auth_headers, session_factory)
    _, spare, scheme, _ = source(client, auth_headers, pump)
    item = part(client, auth_headers, pump).json()
    _hotspot(client, auth_headers, scheme)
    kit = _kit(client, auth_headers, pump, source_visual_page_id=spare).json()
    assert client.post(f"{BASE}/repair-kits/{kit['id']}/components", headers=auth_headers,
                       json={"part_id": item["id"], "quantity": 1}).status_code == 201
    with session_factory() as db:
        owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        report = owner_preview(db, owner, ResourceType.CATALOG_DEFINITION, catalog_id)
        counts = {item["code"]: item["count"] for item in report["owned_records_to_delete"]}
        assert report["can_delete"]
        assert counts["catalog_revision_position_hotspots"] == 1
        assert counts["catalog_revision_repair_kits"] == 1
        assert counts["catalog_revision_repair_kit_components"] == 1
    path = f"/api/owner/data-deletion/catalog_definition/{catalog_id}"
    preview_response = client.get(f"{path}/preview", headers=auth_headers)
    assert preview_response.status_code == 200
    response = client.post(f"{path}/execute", headers=auth_headers, json={
        "current_password": os.environ["ADMIN_PASSWORD"],
        "confirmation_text": preview_response.json()["confirmation_text"],
    })
    assert response.status_code == 200
    with session_factory() as db:
        assert db.get(CatalogDefinition, catalog_id) is None
        assert db.scalar(select(func.count(CatalogRevisionPositionHotspot.id))) == 0
        assert db.scalar(select(func.count(CatalogRevisionRepairKit.id))) == 0


def test_database_rejects_out_of_bounds_hotspot_and_invalid_component_quantity(
    client, auth_headers, session_factory,
):
    _, _, pump, _ = workspace(client, auth_headers, session_factory)
    _, _, scheme, _ = source(client, auth_headers, pump)
    item = part(client, auth_headers, pump).json()
    kit = _kit(client, auth_headers, pump).json()
    with session_factory() as db:
        owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        db.add(CatalogRevisionPositionHotspot(visual_page_id=scheme, position="12", x=.9, y=.1,
                                              width=.2, height=.1, created_by_id=owner.id))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        db.add(CatalogRevisionRepairKitComponent(kit_id=kit["id"], part_id=item["id"],
                                                 quantity=0, created_by_id=owner.id))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
