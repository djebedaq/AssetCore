"""Actual extraction -> human acceptance -> immutable publication, without CSV."""

import hashlib

import fitz
import pytest
from app.catalog_admin.ingest import extraction
from app.catalog_admin.ingest.process import configuration
from app.models import (
    AssetCategory,
    AuditLog,
    CatalogIngestCandidate,
    CatalogRevisionArtifact,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
    CatalogSourceBlob,
    Machine,
    TechnicalDocument,
    TechnicalDocumentRevision,
)
from app.settings import settings
from catalog_ingest_fixtures import cyrillic_manual, encrypted, manual, over_12_mib, scanned
from sqlalchemy import func, select

BASE = "/api/admin/catalog-builder"


def test_failed_rerun_explicit_manual_fallback_preserves_human_data(client, auth_headers, session_factory, monkeypatch):
    from app.catalog_admin.ingest import candidates

    _, revision = workspace(client, auth_headers, session_factory)
    artifact = checked(upload(client, auth_headers, revision, manual()), 201)
    run = analyze(client, auth_headers, artifact)
    for kind in ['GROUP', 'PAGE']:
        for row in proposals(client, auth_headers, run, kind):
            checked(decide(client, auth_headers, run, row))
    part = checked(decide(client, auth_headers, run, proposals(client, auth_headers, run, 'PART')[0]))
    hotspot = next(row for row in proposals(client, auth_headers, run, 'HOTSPOT') if row['payload']['position'] == part['payload']['position'])
    checked(decide(client, auth_headers, run, hotspot))
    actual = candidates.store_page
    def fail_second(db, job, number, layout):
        if number == 2:
            raise RuntimeError('QA failure with private diagnostics')
        return actual(db, job, number, layout)
    monkeypatch.setattr(candidates, 'store_page', fail_second)
    checked(client.post(f"{BASE}/analyses/{run['id']}/retry?rerun=true", headers=auth_headers))
    checked(client.post(f"{BASE}/analyses/{run['id']}/advance", headers=auth_headers))
    failed = checked(client.post(f"{BASE}/analyses/{run['id']}/advance", headers=auth_headers))
    assert failed['status'] == 'FAILED' and failed['error_code'] == 'catalog_ingest_failed'
    assert 'private diagnostics' not in str(failed)
    dismissed = checked(client.post(f"{BASE}/analyses/{run['id']}/dismiss", headers=auth_headers))
    assert dismissed['status'] == 'DISMISSED'
    with session_factory() as db:
        assert db.get(CatalogRevisionPart, part['target_id']).part_number == part['payload']['part_number']
        assert db.get(CatalogIngestCandidate, part['id']).state == 'ACCEPTED'
        assert all(row.state in {'ACCEPTED', 'REJECTED'} for row in db.scalars(select(CatalogIngestCandidate)).all())
    ready = checked(client.get(f"{BASE}/revisions/{revision['id']}/publication-readiness", headers=auth_headers))
    assert not any(error['code'] in {'catalog_ingest_review_required', 'catalog_ingest_not_completed'} for error in ready['errors'])
    assert not ready['ready']  # Existing unverified-hotspot gate is still authoritative.
    assert any(error['code'] == 'catalog_publication_hotspot_unverified' for error in ready['errors'])


def checked(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def workspace(client, headers, factory):
    with factory() as db:
        category = AssetCategory(code="QA_AUTO_INGEST", name_bg="QA", name_en="QA", name_ru="QA",
                                 capabilities=["HAS_PARTS_CATALOG"])
        db.add(category)
        db.commit()
        category_id = category.id
    catalog = checked(client.post(f"{BASE}/simple/catalogs", headers=headers,
        json={"name": "QA extraction", "asset_category_id": category_id}), 201)
    revision = checked(client.get(f"{BASE}/catalogs/{catalog['id']}/revisions", headers=headers))[0]
    return catalog, revision


def upload(client, headers, revision, content):
    return client.post(f"{BASE}/revisions/{revision['id']}/pdf", headers=headers,
                       files={"file": ("qa.pdf", content, "application/octet-stream")})


def analyze(client, headers, artifact):
    run = checked(client.post(f"{BASE}/artifacts/{artifact['id']}/analysis", headers=headers))
    while run["status"] == "RUNNING":
        run = checked(client.post(f"{BASE}/analyses/{run['id']}/advance", headers=headers))
    assert run["status"] == "COMPLETED", run
    return run


def proposals(client, headers, run, kind):
    return checked(client.get(f"{BASE}/analyses/{run['id']}/candidates?kind={kind}&limit=100", headers=headers))["items"]


def decide(client, headers, run, row, action="ACCEPT", **extra):
    return client.post(f"{BASE}/analyses/{run['id']}/candidates/{row['id']}/review", headers=headers,
        json={"action": action, "expected_version": row["version"], **extra})


@pytest.mark.parametrize("item_description", [False, True])
def test_actual_ingestion_happy_path_publication_binding_and_shared_bytes(client, auth_headers, session_factory, machine_ids, item_description):
    catalog, revision = workspace(client, auth_headers, session_factory)
    content = manual(groups=2, item_description=item_description)
    artifact = checked(upload(client, auth_headers, revision, content), 201)
    assert artifact["sha256"] == hashlib.sha256(content).hexdigest()
    duplicate = checked(upload(client, auth_headers, revision, content), 201)
    assert duplicate["id"] == artifact["id"] and duplicate["duplicate"]
    run = analyze(client, auth_headers, artifact)
    assert run["counts"] == {"GROUP": 2, "PAGE": 4, "PART": 8, "HOTSPOT": 8}
    assert checked(client.post(f"{BASE}/artifacts/{artifact['id']}/analysis", headers=auth_headers))["id"] == run["id"]
    for kind in ["GROUP", "PAGE", "PART", "HOTSPOT"]:
        rows = proposals(client, auth_headers, run, kind)
        if kind == 'PART':
            for row in rows:
                assert row['evidence']['bbox'] and row['evidence']['raw_text']
                assert row['payload']['quantity'] == '2.5' and row['page_number'] in [2, 4]
            checked(client.post(f"{BASE}/analyses/{run['id']}/bulk-review", headers=auth_headers,
                json={'action': 'ACCEPT', 'items': [{'id': row['id'], 'expected_version': row['version']} for row in rows]}))
            continue
        for row in rows:
            if kind == "PART":
                assert row["evidence"]["bbox"] and row["evidence"]["raw_text"]
                assert row["payload"]["quantity"] == "2.5"
                assert row["page_number"] in [2, 4]
            result = checked(decide(client, auth_headers, run, row))
            if kind == "HOTSPOT":
                assert not result["payload"].get("verified")
                blocked = checked(client.get(f"{BASE}/revisions/{revision['id']}/publication-readiness", headers=auth_headers))
                assert not blocked["ready"]
                checked(decide(client, auth_headers, run, result, "VERIFY"))
    with session_factory() as db:
        assert db.scalar(select(func.count(CatalogSourceBlob.id))) == 1
        aliases = db.scalars(select(CatalogRevisionArtifact)).all()
        assert len(aliases) == 2 and all(row.stored_content == b"" and row.content == content for row in aliases)
        assert db.scalar(select(func.count(CatalogRevisionPartPageMap.id))) == 8
        assert all(row.name_bg is None and row.name_en is None and row.name_ru is None
                   for row in db.scalars(select(CatalogRevisionPart)).all())
        assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "CATALOG_ANALYSIS_COMPLETED")) == 1
    ready = checked(client.get(f"{BASE}/revisions/{revision['id']}/publication-readiness", headers=auth_headers))
    assert ready["ready"], ready
    checked(client.post(f"{BASE}/revisions/{revision['id']}/publish", headers=auth_headers, json={
        "expected_publication_digest": ready["publication_digest"],
        "expected_current_published_revision_id": None, "confirmed": True}))
    assert client.post(f"{BASE}/analyses/{run['id']}/retry?rerun=true", headers=auth_headers).status_code == 409
    with session_factory() as db:
        assert all(row.uploaded_bytes is None and row.uploaded_content == content
                   for row in db.scalars(select(TechnicalDocument).where(TechnicalDocument.builder_artifact_id.is_not(None))))
        assert all(row.stored_content is None and row.content == content
                   for row in db.scalars(select(TechnicalDocumentRevision).where(TechnicalDocumentRevision.source_blob_id.is_not(None))))
    # Synthetic compatible machines belong only to this disposable test database.
    with session_factory() as db:
        machines = [Machine(inventory_number=f"QA_AUTO_{index}", brand="QA", model="QA", serial_number=f"QA-{index}",
            category_id=catalog["asset_category_id"], category="QA_AUTO_INGEST", name="QA ONLY") for index in range(2)]
        db.add_all(machines)
        db.commit()
        compatible = [machine.id for machine in machines]
    for machine_id in compatible:
        checked(client.post(f"{BASE}/catalogs/{catalog['id']}/assets/{machine_id}", headers=auth_headers), 201)
        result = checked(client.get(f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers))
        assert result["supported"] and len(result["assemblies"]) == 2


@pytest.mark.parametrize("options", [dict(), {"language": "de"}, {"landscape": True}, {"rotated": True},
    {"both": True}, {"groups": 3}, {"multipage": True}, {"wrapped": True}, {"repeated": True}, {"missing": True}])
def test_generic_native_layout_cases(options):
    with fitz.open(stream=manual(**options), filetype="pdf") as pdf:
        pages = [extraction.extract_page(page, configuration(settings)) for page in pdf]
    rows = [row for page in pages for row in page["rows"]]
    assert rows and {row["payload"]["position"] for row in rows} == {"1", "13A", "13.1", "A12"}
    assert all(row["payload"]["part_number"].startswith("QA-") for row in rows)
    assert any(page["role"] in {"BOTH", "EXPLODED_SCHEME"} for page in pages)
    assert all(not page["ocr_used"] for page in pages)
    if options.get("wrapped"):
        assert all("continued description" in row["payload"]["description"] for row in rows)
    if options.get("both"):
        assert pages[0]["role"] == "BOTH"
    if options.get("rotated"):
        assert pages[0]["rotation"] == 90


def test_uncertainty_rejection_idempotence_and_human_edit_survive_rerun(client, auth_headers, session_factory):
    _, revision = workspace(client, auth_headers, session_factory)
    artifact = checked(upload(client, auth_headers, revision, manual(repeated=True, missing=True)), 201)
    run = analyze(client, auth_headers, artifact)
    rows = proposals(client, auth_headers, run, "HOTSPOT")
    assert {row["payload"]["match"] for row in rows} == {"EXACT", "MULTIPLE_CANDIDATES", "NOT_FOUND"}
    for row in proposals(client, auth_headers, run, "GROUP") + proposals(client, auth_headers, run, "PAGE"):
        checked(decide(client, auth_headers, run, row))
    part = proposals(client, auth_headers, run, "PART")[0]
    edited = checked(decide(client, auth_headers, run, part, "EDIT", edit={"part": {
        **{key: part["payload"][key] for key in ["position", "part_number", "quantity", "quantity_raw"]},
        "description": "Human corrected source", }}))
    accepted = checked(decide(client, auth_headers, run, edited))
    rejected = checked(decide(client, auth_headers, run, rows[0], "REJECT"))
    assert decide(client, auth_headers, run, part).status_code == 409
    checked(client.post(f"{BASE}/analyses/{run['id']}/retry?rerun=true", headers=auth_headers))
    run = analyze(client, auth_headers, artifact)
    with session_factory() as db:
        preserved = db.get(CatalogIngestCandidate, accepted["id"])
        assert preserved.payload["description"] == "Human corrected source" and preserved.state == "ACCEPTED"
        assert db.get(CatalogIngestCandidate, rejected["id"]).state == "REJECTED"
        assert db.get(CatalogRevisionPart, accepted["target_id"]).description == "Human corrected source"
        assert db.scalar(select(func.count(CatalogRevisionPart.id))) == 1


def test_binary_limits_invalid_encrypted_large_and_exact_bytes(client, auth_headers, session_factory, monkeypatch):
    _, revision = workspace(client, auth_headers, session_factory)
    assert upload(client, auth_headers, revision, b"%PDF-not-valid").status_code == 422
    response = upload(client, auth_headers, revision, encrypted())
    assert response.status_code == 422 and response.json()["detail"]["code"] == "catalog_source_encrypted"
    monkeypatch.setattr(settings, "catalog_pdf_max_pages", 1)
    response = upload(client, auth_headers, revision, manual())
    assert response.status_code == 413 and response.json()["detail"]["configurable_setting"] == "CATALOG_PDF_MAX_PAGES"
    monkeypatch.setattr(settings, "catalog_pdf_max_pages", 5000)
    monkeypatch.setattr(settings, "catalog_pdf_max_bytes", 1024)
    assert upload(client, auth_headers, revision, manual()).status_code == 413
    monkeypatch.setattr(settings, "catalog_pdf_max_bytes", 256 * 1024 * 1024)
    large = over_12_mib()
    assert len(large) > 12 * 1024 * 1024
    artifact = checked(upload(client, auth_headers, revision, large), 201)
    downloaded = client.get(f"{BASE}/artifacts/{artifact['id']}/download", headers=auth_headers)
    assert downloaded.content == large


def test_selective_ocr_disabled_and_unavailable(monkeypatch):
    with fitz.open(stream=scanned(mixed=True), filetype="pdf") as pdf:
        config = {**configuration(settings), "ocr_enabled": False}
        scan = extraction.extract_page(pdf[0], config)
        native = extraction.extract_page(pdf[2], config)
        assert "OCR_DISABLED" in scan["warnings"] and scan["role"] == "AMBIGUOUS"
        assert native["rows"] and "OCR_DISABLED" not in native["warnings"]
        def unavailable(*args, **kwargs):
            raise RuntimeError("QA unavailable")
        monkeypatch.setattr(fitz.Page, "get_textpage_ocr", unavailable)
        result = extraction.extract_page(pdf[0], configuration(settings))
        assert "OCR_UNAVAILABLE" in result["warnings"] and not result["ocr_used"]


def test_bulk_review_transaction_rollback_and_permissions(client, auth_headers, session_factory):
    _, revision = workspace(client, auth_headers, session_factory)
    artifact = checked(upload(client, auth_headers, revision, manual()), 201)
    run = analyze(client, auth_headers, artifact)
    groups = proposals(client, auth_headers, run, "GROUP")
    parts = proposals(client, auth_headers, run, "PART")
    response = client.post(f"{BASE}/analyses/{run['id']}/bulk-review", headers=auth_headers, json={"action": "ACCEPT",
        "items": [{"id": row["id"], "expected_version": row["version"]} for row in groups + parts]})
    assert response.status_code == 422
    assert proposals(client, auth_headers, run, "GROUP")[0]["state"] != "ACCEPTED"
    assert client.get(f"{BASE}/analyses/{run['id']}").status_code == 401


@pytest.mark.parametrize("language", ["bg", "ru"])
def test_cyrillic_native_bom(language):
    with fitz.open(stream=cyrillic_manual(language), filetype="pdf") as pdf:
        page = extraction.extract_page(pdf[0], configuration(settings))
    assert page["role"] == "SPARE_PARTS_LIST"
    assert page["rows"][0]["payload"]["part_number"] == "QA-001"
    assert page["rows"][0]["payload"]["quantity"] == "1.5"
    assert "упл" in page["rows"][0]["payload"]["description"]


def test_ocr_layout_is_distinct_cached_evidence_and_never_native_confidence(monkeypatch):
    with fitz.open(stream=manual(), filetype="pdf") as native, fitz.open(stream=scanned(mixed=True), filetype="pdf") as scan:
        calls = []
        native_page = native[1]
        def ocr(self, **kwargs):
            import weakref
            calls.append(kwargs)
            textpage = native_page.get_textpage()
            textpage.parent = weakref.proxy(self)
            return textpage
        monkeypatch.setattr(extraction.ocr, "textpage", lambda page, config: ocr(page, **config))
        recognized = extraction.extract_page(scan[0], configuration(settings))
        assert recognized["ocr_used"] and recognized["method"] == "OCR"
        assert recognized["rows"] and all(row["confidence"] <= .7 for row in recognized["rows"])
        assert all("OCR_REQUIRES_REVIEW" in row["warnings"] for row in recognized["rows"])
        extraction.extract_page(scan[2], configuration(settings))
        assert len(calls) == 1


def test_ambiguity_multiple_occurrences_and_rotation_geometry(client, auth_headers, session_factory):
    _, revision = workspace(client, auth_headers, session_factory)
    artifact = checked(upload(client, auth_headers, revision, manual(repeated=True, rotated=True)), 201)
    run = analyze(client, auth_headers, artifact)
    for kind in ["GROUP", "PAGE", "PART"]:
        for row in proposals(client, auth_headers, run, kind):
            checked(decide(client, auth_headers, run, row))
    row = next(row for row in proposals(client, auth_headers, run, "HOTSPOT") if row["payload"]["position"] == "13A")
    assert row["payload"]["match"] == "MULTIPLE_CANDIDATES"
    assert decide(client, auth_headers, run, row).status_code == 422
    locations = row["payload"]["locations"]
    assert len(locations) == 2
    for location in locations:
        assert 0 <= location["x"] <= 1 and 0 <= location["y"] <= 1
        assert .002 <= location["width"] < .1 and .002 <= location["height"] < .1
        assert location["x"] > .5  # 90-degree rotation moves y=200 labels to the right.
    accepted = checked(decide(client, auth_headers, run, row, locations=[0, 1]))
    assert len(accepted["payload"]["accepted_hotspots"]) == 2
    checked(decide(client, auth_headers, run, accepted, "VERIFY"))


def test_deleted_source_id_reuse_cannot_accept_a_group_against_another_pdf(client, auth_headers, session_factory):
    _, revision = workspace(client, auth_headers, session_factory)
    original = checked(upload(client, auth_headers, revision, manual()), 201)
    run = analyze(client, auth_headers, original)
    group = proposals(client, auth_headers, run, "GROUP")[0]
    assert client.delete(f"{BASE}/artifacts/{original['id']}", headers=auth_headers).status_code == 204
    replacement = checked(upload(client, auth_headers, revision, manual(groups=2)), 201)
    assert replacement['id'] == original['id']  # SQLite reuses the deleted highest integer PK.
    assert replacement['sha256'] != original['sha256']
    response = decide(client, auth_headers, run, group)
    assert response.status_code == 404
    assert response.json()['detail']['code'] == 'catalog_source_not_found'
    with session_factory() as db:
        assert db.get(CatalogIngestCandidate, group['id']).state == 'PROPOSED'
        assert db.get(CatalogRevisionArtifact, replacement['id']).sha256 == replacement['sha256']
    # Retained original-byte evidence remains accessible despite deleting its draft alias.
    preview = client.get(f"{BASE}/analyses/{run['id']}/pages/1/preview", headers=auth_headers)
    assert preview.status_code == 200 and preview.content.startswith(b'\x89PNG')
