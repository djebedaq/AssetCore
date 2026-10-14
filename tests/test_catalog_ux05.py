"""Real HTTP publication/part requests, reused against migrated PostgreSQL."""
import json

import pytest
from app.catalog_admin.parts_extraction import ledger
from app.models import (
    AuditLog,
    CatalogDefinition,
    CatalogPositionHotspot,
    CatalogRevision,
    CatalogRevisionArtifact,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
    CatalogSourceReviewDecision,
    Machine,
    PartCatalog,
)
from catalog_review_helpers import verify_http_source
from catalog_ux05_fixtures import publication_pdf
from sqlalchemy import func, inspect, select
from test_catalog_durable_review import resume
from test_catalog_guided_builder import assign
from test_catalog_selected_extraction import BASE, checked, upload, workspace


def setup(client, headers, factory, coverage=0, attested=False, inspected=False):
    catalog, revision = workspace(client, headers, factory)
    assembly = checked(client.get(f"{BASE}/revisions/{revision['id']}/assemblies", headers=headers))[0]
    page = checked(client.post(f"{BASE}/assemblies/{assembly['id']}/reference-pages", headers=headers, json={}), 201)
    artifact = checked(upload(client, headers, revision, publication_pdf()), 201)
    page = assign(client, headers, page, artifact, [1, 2, 3], "EXPLODED_SCHEME")
    page = assign(client, headers, page, artifact, [4, 5, 6, 7], "SPARE_PARTS_LIST")
    for source in [s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST"]:
        preview = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extract", headers=headers,
                                      json={"visual_page_id": source["id"]}))
        inspection = None
        if inspected:
            state = next(s for s in resume(client, headers, page)["sources"] if s["visual_page_id"] == source["id"])
            image = client.get(f"{BASE}/visual-pages/{source['id']}/review-original", headers=headers)
            assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
            inspection = {"expected_version": state["version"], "fingerprint": state["fingerprint"],
                          "inspection_token": image.headers["X-Catalog-Review-Receipt"]}
        data = {"token": preview["token"], "rows": [{"index": i, "part": row["payload"],
                "expected_version": row["candidate_version"]} for i, row in enumerate(preview["rows"])],
                "confirm_warnings": True, "inspection": inspection}
        checked(client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=headers, json=data))
    parts = checked(client.get(f"{BASE}/reference-pages/{page['id']}/parts", headers=headers))
    assert len(parts) == 59
    schemes = [s for s in page["sources"] if s["role"] == "EXPLODED_SCHEME"]
    for position in range(1, coverage + 1):
        scheme = schemes[(position - 1) // 20]
        marker = checked(client.post(f"{BASE}/visual-pages/{scheme['id']}/hotspots", headers=headers,
            json={"position": str(position), "x": .09 + (position - 1) % 5 * .16,
                  "y": .16 + (position - 1) % 20 // 5 * .15, "width": .04, "height": .04}), 201)
        checked(client.post(f"{BASE}/hotspots/{marker['id']}/verify", headers=headers,
                            json={"expected_version": marker["version"]}))
    if attested:
        verify_http_source(client, headers, resume(client, headers, page)["sources"][0], manual=False)
    return catalog, revision, assembly, page, artifact, parts


def ready(client, headers, revision):
    return checked(client.get(f"{BASE}/revisions/{revision['id']}/publication-readiness", headers=headers))


def publish(client, headers, revision, result):
    return client.post(f"{BASE}/revisions/{revision['id']}/publish", headers=headers, json={
        "expected_publication_digest": result["publication_digest"],
        "expected_current_published_revision_id": result["current_published_revision_id"], "confirmed": True})


def snapshot(db, model):
    columns = [a.key for a in inspect(model).column_attrs]
    return {row.id: tuple(getattr(row, key) for key in columns) for row in db.scalars(select(model))}


@pytest.mark.parametrize("coverage", [59, 45, 0])
def test_confirmed_parts_publish_with_optional_review_and_coverage(client, auth_headers, session_factory, coverage):
    catalog, revision, _, _, _, parts = setup(client, auth_headers, session_factory, coverage, attested=True)
    with session_factory() as db:
        category_id = db.get(CatalogDefinition, catalog["id"]).asset_category_id
        machine = Machine(inventory_number="QA_UX05_ONLY", name="Synthetic QA only", category="QA_AUTO_INGEST",
                          category_id=category_id, brand="QA", model="QA")
        db.add(machine)
        db.commit()
        machine_id = machine.id
        history = {model: snapshot(db, model) for model in [ledger.Candidate, ledger.Source, ledger.Attempt,
                   CatalogSourceReviewDecision, CatalogRevisionPart, AuditLog]}
    result = ready(client, auth_headers, revision)
    assert result["ready"] and not result["errors"]
    assert result["summary"]["reviewed_source_count"] == 1
    assert len([w for w in result["warnings"] if w["code"] == "catalog_publication_source_review_required"]) == 3
    coverage_warnings = [w for w in result["warnings"] if w["code"] == "catalog_publication_hotspot_coverage"]
    assert sum(w["missing_positions"] for w in coverage_warnings) == 59 - coverage
    checked(publish(client, auth_headers, revision, result))
    with session_factory() as db:
        for model, before in history.items():
            after = snapshot(db, model)
            assert before == {key: after[key] for key in before}
        assert db.scalar(select(func.count(CatalogSourceReviewDecision.id))) == 1
        runtime_parts = list(db.scalars(select(PartCatalog).where(PartCatalog.builder_revision_id == revision["id"])))
        assert len(runtime_parts) == 59
        assert all(p.is_verified and p.verification_status == "CONFIRMED_BUILDER_PUBLICATION" for p in runtime_parts)
        for part in runtime_parts:
            original = db.get(CatalogRevisionPart, part.builder_part_id)
            assert part.verified_by_id == original.extraction_evidence["confirmed_by_id"]
            assert part.verified_at == original.created_at
        assert db.scalar(select(func.count(CatalogPositionHotspot.id)).where(
            CatalogPositionHotspot.builder_revision_id == revision["id"])) == coverage
        event = db.scalar(select(AuditLog).where(AuditLog.action == "CATALOG_REVISION_PUBLISHED",
                                                AuditLog.entity_id == revision["id"]))
        assert json.loads(event.details)["reviewed_source_count"] == 1
    checked(client.post(f"{BASE}/catalogs/{catalog['id']}/assets/{machine_id}", headers=auth_headers,
                        json={"compatibility_confirmed": True}), 201)
    runtime = checked(client.get(f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers))
    source_id = runtime["assemblies"][0]["pages"][0]["source_id"]
    detail = checked(client.get(f"/api/catalog/v2/assemblies/{source_id}?machine_id={machine_id}", headers=auth_headers))
    assert len(detail["parts"]) == 59
    found = checked(client.get(f"/api/catalog/v2/search?machine_id={machine_id}&q=QA-UX05-059", headers=auth_headers))
    assert len(found) == 1
    selected = found[0]
    checked(client.post("/api/part-requests/multi", headers=auth_headers, json={"machine_id": machine_id,
        "lines": [{"part_id": selected["id"], "description": selected["description"], "quantity": 1}]}), 201)
    status = client.patch(f"{BASE}/parts/{parts[0]['id']}", headers=auth_headers,
                          json={"description": "QA forbidden published edit"}).status_code
    assert status == 409


def test_old_accepted_parts_and_same_flow_inspection_need_no_source_attestation(client, auth_headers, session_factory):
    _, revision, _, page, _, parts = setup(client, auth_headers, session_factory, inspected=True)
    states = resume(client, auth_headers, page)["sources"]
    assert all(s["review_state"] != "VERIFIED" for s in states)
    assert all(c["state"] == "ACCEPTED" for s in states for c in s["candidates"])
    with session_factory() as db:
        confirmations = list(db.scalars(select(AuditLog).where(AuditLog.action == "SPARE_PARTS_CONFIRMED")))
        assert len(confirmations) == 4
        assert all(json.loads(a.details)["inspection"]["inspection_digest"] for a in confirmations)
        assert db.scalar(select(func.count(CatalogSourceReviewDecision.id))) == 0
    # Resume and edit an already accepted row; no reacceptance or source decision.
    checked(client.patch(f"{BASE}/parts/{parts[0]['id']}", headers=auth_headers, json={"quantity": "3"}))
    result = ready(client, auth_headers, revision)
    assert result["ready"] and result["summary"]["reviewed_source_count"] == 0
    checked(publish(client, auth_headers, revision, result))
    status = client.patch(f"{BASE}/parts/{parts[0]['id']}", headers=auth_headers, json={"quantity": "4"}).status_code
    assert status == 409


@pytest.mark.parametrize("damage,code", [
    ("sha", "catalog_publication_source_invalid"),
    ("mapping", "catalog_publication_part_mapping_invalid"),
    ("part", "catalog_publication_part_incomplete"),
    ("conflict", "catalog_publication_candidate_conflict"),
    ("accepted_link", "catalog_publication_candidate_mapping_invalid"),
    ("conflict_selection", "catalog_publication_candidate_conflict"),
    ("evidence", "catalog_publication_extraction_integrity"),
    ("provenance_mapping", "catalog_publication_candidate_mapping_invalid"),
])
def test_actual_integrity_errors_remain_blocking(client, auth_headers, session_factory, damage, code):
    _, revision, _, _, artifact, parts = setup(client, auth_headers, session_factory)
    with session_factory() as db:
        if damage == "sha":
            db.get(CatalogRevisionArtifact, artifact["id"]).sha256 = "0" * 64
        elif damage == "mapping":
            mapping = db.scalar(select(CatalogRevisionPartPageMap))
            mapping.visual_page_id = db.scalar(select(ledger.CatalogRevisionVisualPage.id).where(
                ledger.CatalogRevisionVisualPage.role == "EXPLODED_SCHEME"))
        elif damage == "part":
            db.get(CatalogRevisionPart, parts[0]["id"]).part_number = ""
        elif damage == "evidence":
            db.scalar(select(ledger.Attempt)).evidence_digest = "0" * 64
        elif damage == "provenance_mapping":
            mapping = db.scalar(select(CatalogRevisionPartPageMap))
            mapping.visual_page_id = db.scalar(select(ledger.CatalogRevisionVisualPage.id).where(
                ledger.CatalogRevisionVisualPage.role == "SPARE_PARTS_LIST",
                ledger.CatalogRevisionVisualPage.id != mapping.visual_page_id))
            # Also protect old accepted parts when there is no current accepted
            # ledger link to detect the mismatch on their behalf.
            db.scalar(select(ledger.Candidate).where(ledger.Candidate.part_id == mapping.part_id)).state = "PENDING"
        else:
            candidate = db.scalar(select(ledger.Candidate))
            if damage in {"conflict", "conflict_selection"}:
                if damage == "conflict_selection":
                    db.get(CatalogRevisionArtifact, artifact["id"]).title = "QA changed selection"
                candidate.state = "CONFLICT"
            else:
                candidate.part_id = parts[-1]["id"]
        db.commit()
    result = ready(client, auth_headers, revision)
    assert not result["ready"] and code in {e["code"] for e in result["errors"]}
    response = publish(client, auth_headers, revision, result)
    assert response.status_code == 409
    with session_factory() as db:
        assert db.scalar(select(func.count(PartCatalog.id)).where(PartCatalog.builder_revision_id == revision["id"])) == 0


@pytest.mark.parametrize("change", ["part", "source"])
def test_stale_digest_never_materializes(client, auth_headers, session_factory, change):
    _, revision, _, _, artifact, parts = setup(client, auth_headers, session_factory)
    result = ready(client, auth_headers, revision)
    if change == "part":
        checked(client.patch(f"{BASE}/parts/{parts[0]['id']}", headers=auth_headers, json={"quantity": "3"}))
    else:
        with session_factory() as db:
            db.get(CatalogRevisionArtifact, artifact["id"]).title = "QA changed source title"
            db.commit()
    response = publish(client, auth_headers, revision, result)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "catalog_publication_stale"
    with session_factory() as db:
        assert db.get(CatalogRevision, revision["id"]).status == "DRAFT"
        assert db.scalar(select(func.count(PartCatalog.id)).where(PartCatalog.builder_revision_id == revision["id"])) == 0


def test_unverified_marker_stays_unverified_and_hidden(client, auth_headers, session_factory):
    _, revision, _, page, _, _ = setup(client, auth_headers, session_factory)
    scheme = next(s for s in page["sources"] if s["role"] == "EXPLODED_SCHEME")
    checked(client.post(f"{BASE}/visual-pages/{scheme['id']}/hotspots", headers=auth_headers,
        json={"position": "1", "x": .2, "y": .2, "width": .02, "height": .02}), 201)
    result = ready(client, auth_headers, revision)
    assert result["ready"] and "catalog_publication_hotspot_unverified" in {w["code"] for w in result["warnings"]}
    checked(publish(client, auth_headers, revision, result))
    from app.catalog.repository import hotspots_for_diagram
    with session_factory() as db:
        marker = db.scalar(select(CatalogPositionHotspot).where(CatalogPositionHotspot.builder_revision_id == revision["id"]))
        assert not marker.is_verified and marker.verified_by_id is None and marker.verified_at is None
        assert hotspots_for_diagram(db, marker.diagram_id, verified_only=True) == []
        assert len(hotspots_for_diagram(db, marker.diagram_id, verified_only=False)) == 1


def test_legacy_assembly_scope_allows_zero_markers_but_rejects_invalid_geometry(client, auth_headers, session_factory):
    from app.models import CatalogRevisionPositionHotspot
    from catalog_review_fix_helpers import context, draft
    with session_factory() as db:
        actor, category, _ = context(db)
        _, revision, _ = draft(db, actor, category, "UX05_LEGACY", 1)
        revision_id = revision.id
        marker = db.scalar(select(CatalogRevisionPositionHotspot))
        marker_id, version = marker.id, marker.version
    revision = {"id": revision_id}
    status = client.patch(f"{BASE}/hotspots/{marker_id}", headers=auth_headers,
        json={"expected_version": version, "x": 2}).status_code
    assert status == 422
    with session_factory() as db:
        db.delete(db.get(CatalogRevisionPositionHotspot, marker_id))
        db.commit()
    result = ready(client, auth_headers, revision)
    assert result["ready"]
    assert any(w["code"] == "catalog_publication_hotspot_coverage" for w in result["warnings"])
    checked(publish(client, auth_headers, revision, result))
