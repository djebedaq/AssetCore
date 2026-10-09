"""Disposable ASSETCORE-02 identity, reference and registry acceptance cases."""

from datetime import datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.catalog.runtime_context import require_compatible_kit, require_compatible_part
from app.catalog.service import machine_family
from app.machine_identity import FALCH_500_CORRECTIONS
from app.models import (
    AuditLog,
    CatalogAssetBinding,
    CatalogReferenceAssociation,
    CatalogRevision,
    Machine,
    OfficialDocumentVersion,
    PartCatalog,
    PartRequest,
    RepairKit,
    User,
)
from app.registry_correction import apply_correction, preflight
from app.seed import seed_database
from fastapi import HTTPException
from sqlalchemy import func, select
from test_catalog_builder_parts import BASE, part, source, workspace
from test_official_document_registry import _add_official_document, _seed_registry_scenario


def legacy(db):
    for serial, (old, _) in reversed(FALCH_500_CORRECTIONS.items()):
        machine = db.scalar(select(Machine).where(Machine.serial_number == serial))
        machine.inventory_number, machine.name = old, f"HPWJ №{old}"
        db.flush()


def test_identity_preserves_ids_signed_bytes_and_seed(session_factory):
    with session_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        legacy(db)
        machines = list(db.scalars(select(Machine).order_by(Machine.id)))
        before = {m.id: (m.serial_number, m.brand, m.model, m.inventory_number) for m in machines}
        target = next(m for m in machines if m.serial_number == "G39300296")
        document = _add_official_document(db, number="QA-IDENTITY-SIGNED", document_type="REPAIR_PROTOCOL",
            actor_id=actor.id, created_at=datetime(2026, 9, 1), machine_id=target.id,
            snapshot={"machine_number": "9", "machine_id": target.id}, status="SIGNED", signed_slots=("MECHANIC",))
        db.commit()
        version = db.get(OfficialDocumentVersion, document.current_version_id)
        evidence = (version.snapshot, version.docx_content, version.pdf_content, version.signing_sha256)
        report = preflight(db)
        assert report["ready"] and not report["already_corrected"]
        seed_database(db)
        assert db.get(Machine, target.id).inventory_number == "9"
        assert db.scalar(select(func.count(Machine.id))) == 19
        apply_correction(db, actor, approved_fingerprint=report["fingerprint"], reason="QA verified factory register")
        db.commit()
        for serial, (_, new) in FALCH_500_CORRECTIONS.items():
            machine = db.scalar(select(Machine).where(Machine.serial_number == serial))
            assert machine.inventory_number == new
            assert machine.id in before and before[machine.id][:3] == (machine.serial_number, machine.brand, machine.model)
            assert machine_family(machine) == "FALCH_500"
        assert (version.snapshot, version.docx_content, version.pdf_content, version.signing_sha256) == evidence
        assert document.machine_id == target.id
        assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "registry_inventory_correction")) == 4
        corrected = preflight(db)
        assert corrected["already_corrected"]
        apply_correction(db, actor, approved_fingerprint=corrected["fingerprint"], reason="QA repeat")
        db.commit()
        assert db.scalar(select(func.count(Machine.id))) == 19
        assert db.scalar(select(Machine).where(Machine.inventory_number == "6")) is None
        assert len({m.inventory_number for m in machines}) == 19
        for machine in machines:
            if machine.serial_number not in FALCH_500_CORRECTIONS:
                assert before[machine.id] == (machine.serial_number, machine.brand, machine.model, machine.inventory_number)


@pytest.mark.parametrize("problem", ["conflict", "model", "serial", "number", "mixed", "stale"])
def test_correction_refuses_unverified_states(session_factory, problem):
    with session_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        legacy(db)
        report = preflight(db)
        target = db.scalar(select(Machine).where(Machine.serial_number == "G39300296"))
        if problem == "conflict":
            db.scalar(select(Machine).where(Machine.inventory_number == "4")).inventory_number = "8"
        elif problem == "model":
            target.model = "QA mismatch"
        elif problem == "serial":
            target.serial_number = None
        elif problem == "number":
            target.inventory_number = "QA-invalid"
        elif problem == "mixed":
            target.inventory_number = "8"
        else:
            target.inventory_number, target.name = "8", "QA change"
        db.flush()
        with pytest.raises(ValueError):
            apply_correction(db, actor, approved_fingerprint=report["fingerprint"], reason="QA")
        db.rollback()


def test_all_eight_corrected_falch_physical_identities_keep_original_catalog(client, auth_headers, session_factory):
    with session_factory() as db:
        machines = list(db.scalars(select(Machine).where(Machine.brand == "Falch", Machine.pressure_bar == 500)))
        assert {m.inventory_number for m in machines} == {"8", "9", "10", "11", "13", "14", "15", "16"}
        kit = db.scalar(select(RepairKit).where(RepairKit.family == "FALCH_500"))
        for machine in machines:
            require_compatible_kit(db, machine, kit)
        ids = [m.id for m in machines]
    payload, _ = builtin_selection(client, auth_headers, session_factory)
    payload["machine_ids"] = [ids[0]]
    # A redundant supplemental reference must not narrow the primary catalog.
    original = client.get(f"/api/catalog/v2/assemblies/falch_500_pump?machine_id={ids[0]}", headers=auth_headers).json()
    assert client.post(f"{BASE}/reference-associations", headers=auth_headers, json=payload).status_code == 201
    current = client.get(f"/api/catalog/v2/assemblies/falch_500_pump?machine_id={ids[0]}", headers=auth_headers).json()
    assert len(original["parts"]) > 1 and current["parts"] == original["parts"]
    assert client.get(f"/api/catalog/v2/repair-kits?machine_id={ids[0]}&source_id=falch_500_pump", headers=auth_headers).json()
    for machine_id in ids:
        catalog = client.get(f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers)
        assert catalog.status_code == 200 and catalog.json()["supported"]
        assert catalog.json()["family"] == "FALCH_500"
        assert all(assembly["family"] == "FALCH_500" for assembly in catalog.json()["assemblies"])
    with session_factory() as db:
        machine = db.get(Machine, ids[0])
        machine.serial_number = "QA_UNVERIFIED"
        assert machine_family(machine) is None


def builtin_selection(client, headers, factory):
    sources = client.get(f"{BASE}/reference-sources", headers=headers)
    assert sources.status_code == 200, sources.text
    selected = next(row for row in sources.json() if row["source_id"] == "falch_500_pump")
    scheme = next(page for page in selected["pages"] if page["role"] == "EXPLODED_SCHEME")
    parts_list = next(page for page in selected["pages"] if page["role"] == "SPARE_PARTS_LIST")
    parts = client.get(f"{BASE}/reference-sources/{parts_list['id']}/parts", headers=headers).json()
    with factory() as db:
        machine_ids = list(db.scalars(select(Machine.id).where(Machine.inventory_number.in_(["4", "5"]))))
    return {"machine_ids": machine_ids, "scheme_id": scheme["id"], "parts_list_id": parts_list["id"],
            "source_revision": selected["revision"], "part_ids": [parts[0]["id"]],
            "reason": "Synthetic QA technical confirmation only", "compatibility_confirmed": True}, parts


def test_builtin_references_multiple_machines_exact_variants_and_revoke(client, auth_headers, viewer_headers, session_factory):
    payload, parts = builtin_selection(client, auth_headers, session_factory)
    assert client.post(f"{BASE}/reference-associations", headers=viewer_headers, json=payload).status_code == 403
    for invalid in ({"compatibility_confirmed": False}, {"part_ids": [999999]}, {"source_revision": "DRAFT"},
                    {"parts_list_id": payload["scheme_id"]}):
        assert client.post(f"{BASE}/reference-associations", headers=auth_headers, json={**payload, **invalid}).status_code == 409
    created = client.post(f"{BASE}/reference-associations", headers=auth_headers, json=payload)
    assert created.status_code == 201, created.text
    assert len(created.json()) == 2
    assert client.post(f"{BASE}/reference-associations", headers=auth_headers, json=payload).status_code == 409
    request_ids = []
    for machine_id in payload["machine_ids"]:
        result = client.get(f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers)
        assert result.status_code == 200, result.text
        assert result.json()["supported"] and len(result.json()["references"]) == 1
        assert result.json()["assemblies"][0]["is_supplemental"]
        detail = client.get(f"/api/catalog/v2/assemblies/falch_500_pump?machine_id={machine_id}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        assert [part["id"] for part in detail.json()["parts"]] == payload["part_ids"]
        for diagram in detail.json()["diagrams"]:
            hotspots = client.get(f"/api/catalog/v2/diagrams/{diagram['id']}/hotspots?machine_id={machine_id}", headers=auth_headers)
            assert hotspots.status_code == 200, hotspots.text
            assert all(variant["id"] in payload["part_ids"] for hotspot in hotspots.json() for variant in hotspot["variants"])
        for part_id, expected in ((parts[0]["id"], 201), (parts[1]["id"], 409)):
            request = client.post("/api/part-requests/multi", headers=auth_headers, json={
                "machine_id": machine_id, "lines": [{"catalog_part_id": part_id, "description": "QA reference", "quantity": 1}]})
            assert request.status_code == expected, request.text
            if expected == 201:
                request_ids.append(request.json()["id"])
    with session_factory() as db:
        assert db.scalar(select(func.count(CatalogAssetBinding.id))) == 0
        assert db.scalar(select(func.count(CatalogReferenceAssociation.id))) == 2
    migration_file = Path(__file__).resolve().parents[1] / "backend/alembic/versions/20261009_0032_catalog_reference_associations.py"
    spec = spec_from_file_location("reference_migration", migration_file)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    with session_factory.kw["bind"].begin() as connection, Operations.context(MigrationContext.configure(connection)):
        with pytest.raises(RuntimeError, match="Audited reference history"):
            migration.downgrade()
    revoked = client.post(f"{BASE}/reference-associations/{created.json()[0]['id']}/revoke", headers=auth_headers,
                           json={"reason": "QA incorrect applicability"})
    assert revoked.status_code == 200
    with session_factory() as db:
        row = db.get(CatalogReferenceAssociation, created.json()[0]["id"])
        assert row.revoked_at and db.get(PartRequest, request_ids[0])
        machine = db.get(Machine, row.machine_id)
        with pytest.raises(HTTPException):
            require_compatible_part(db, machine, db.get(PartCatalog, payload["part_ids"][0]))


def test_builder_drafts_excluded_published_revision_pinned(client, auth_headers, session_factory):
    with session_factory() as db:
        machine = db.scalar(select(Machine).where(Machine.inventory_number == "4"))
        machine_id, category_id = machine.id, machine.category_id
    catalog_id, revision_id, assembly_id, _ = workspace(client, auth_headers, session_factory,
        include_empty_group=False, category_id=category_id)
    _, spare, _, _ = source(client, auth_headers, assembly_id)
    part_id = part(client, auth_headers, assembly_id).json()["id"]
    assert client.post(f"{BASE}/parts/{part_id}/source-pages", headers=auth_headers,
                       json={"visual_page_ids": [spare]}).status_code == 201
    assert all(not item["revision"].startswith("CATALOG_BUILDER") for item in client.get(f"{BASE}/reference-sources", headers=auth_headers).json())
    readiness = client.get(f"{BASE}/revisions/{revision_id}/publication-readiness", headers=auth_headers).json()
    published = client.post(f"{BASE}/revisions/{revision_id}/publish", headers=auth_headers, json={
        "expected_publication_digest": readiness["publication_digest"], "expected_current_published_revision_id": None, "confirmed": True})
    assert published.status_code == 200, published.text
    assert client.post(f"{BASE}/catalogs/{catalog_id}/assets/{machine_id}", headers=auth_headers).status_code == 201
    selected = next(item for item in client.get(f"{BASE}/reference-sources", headers=auth_headers).json()
                    if item["revision"] == f"CATALOG_BUILDER_R{revision_id}")
    with session_factory() as db:
        machine_id = db.scalar(select(Machine.id).where(Machine.inventory_number == "4"))
    spare = next(page["id"] for page in selected["pages"] if page["role"] == "SPARE_PARTS_LIST")
    scheme = next(page["id"] for page in selected["pages"] if page["role"] == "EXPLODED_SCHEME")
    runtime_part = client.get(f"{BASE}/reference-sources/{spare}/parts", headers=auth_headers).json()[0]
    created = client.post(f"{BASE}/reference-associations", headers=auth_headers, json={
        "machine_ids": [machine_id], "scheme_id": scheme, "parts_list_id": spare,
        "source_revision": selected["revision"], "part_ids": [runtime_part["id"]],
        "reason": "QA published reference", "compatibility_confirmed": True})
    assert created.status_code == 201, created.text
    supplemental, _ = builtin_selection(client, auth_headers, session_factory)
    assert client.post(f"{BASE}/reference-associations", headers=auth_headers, json=supplemental).status_code == 201
    context = client.get(f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers).json()
    assert len(context["assemblies"]) == 2
    assert not context["assemblies"][0].get("is_supplemental")
    assert context["assemblies"][1]["is_supplemental"]
    with session_factory() as db:
        binding = db.scalar(select(CatalogAssetBinding).where(CatalogAssetBinding.machine_id == machine_id))
        assert binding.catalog_id == catalog_id
    request = client.post("/api/part-requests/multi", headers=auth_headers, json={
        "machine_id": machine_id, "lines": [{"catalog_part_id": runtime_part["id"], "description": "QA", "quantity": 1}]})
    assert request.status_code == 201, request.text
    with session_factory() as db:
        db.get(CatalogRevision, revision_id).status = "RETIRED"
        db.commit()
    context = client.get(f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers).json()
    assert not context["references"][0]["available"]
    assert context["references"][0]["revision"] == selected["revision"]
    assert client.post("/api/part-requests/multi", headers=auth_headers, json={
        "machine_id": machine_id, "lines": [{"catalog_part_id": runtime_part["id"], "description": "QA", "quantity": 1}]}).status_code == 409


def test_registry_filters_use_real_signature_evidence_before_pagination(client, auth_headers, session_factory):
    with session_factory() as db:
        machines = dict(db.execute(select(Machine.inventory_number, Machine.id)).all())
    _seed_registry_scenario(session_factory, machines)
    for signature in ("SIGNED", "PARTIALLY_SIGNED", "UNSIGNED", "UNKNOWN", "NOT_REQUIRED"):
        response = client.get(f"/api/official-documents/registry/items?category=transfers&signature_status={signature}&page_size=1", headers=auth_headers)
        assert response.status_code == 200, response.text
        assert all(item["signature_status"] == signature for item in response.json()["items"])
        if response.json()["total"]:
            assert response.json()["count"] == 1
    response = client.get("/api/official-documents/registry/items?category=transfers&q=G39300297&status=INCOMPLETE&date_from=2026-08-20&date_to=2026-08-20", headers=auth_headers)
    assert response.status_code == 200 and response.json()["total"] == 1, response.text
    assert response.json()["items"][0]["machine_number"] == "9"
    assert client.get("/api/official-documents/registry/items?category=transfers&signature_status=INVALID", headers=auth_headers).status_code == 422
