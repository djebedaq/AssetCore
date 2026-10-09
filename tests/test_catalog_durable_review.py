"""Fail-closed publication and durable human work using synthetic PDFs only."""
import copy
import os
from datetime import timedelta

from app.catalog_admin.parts_extraction import ledger, process, service
from app.models import CatalogExtractionAttempt, CatalogSourceReviewDecision, utcnow
from catalog_review_helpers import verify_http_source
from sqlalchemy import func, select
from test_catalog_guided_builder import assign
from test_catalog_multipage_extraction import multipage_pdf
from test_catalog_selected_extraction import BASE, checked, upload, workspace


def setup_review(client, headers, factory, count=1):
    _, revision = workspace(client, headers, factory)
    assembly = checked(client.get(f"{BASE}/revisions/{revision['id']}/assemblies", headers=headers))[0]
    page = checked(client.post(f"{BASE}/assemblies/{assembly['id']}/reference-pages", headers=headers, json={}), 201)
    artifact = checked(upload(client, headers, revision, multipage_pdf(count=count)), 201)
    page = assign(client, headers, page, artifact, [1], "EXPLODED_SCHEME")
    page = assign(client, headers, page, artifact, list(range(2, count + 2)), "SPARE_PARTS_LIST")
    return revision, assembly, page, artifact


def resume(client, headers, page):
    return checked(client.post(f"{BASE}/reference-pages/{page['id']}/review-session", headers=headers))


def extract(client, headers, page, source):
    return checked(client.post(f"{BASE}/reference-pages/{page['id']}/extract", headers=headers,
        json={"visual_page_id": source["id"]}))


def accept(client, headers, page, preview):
    return checked(client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=headers,
        json={"token": preview["token"], "rows": [{"index": i, "part": r["payload"],
              "expected_version": r["candidate_version"]} for i, r in enumerate(preview["rows"])], "confirm_warnings": True}))


def mark(client, headers, page):
    scheme = next(s for s in page["sources"] if s["role"] == "EXPLODED_SCHEME")
    parts = checked(client.get(f"{BASE}/reference-pages/{page['id']}/parts", headers=headers))
    for i, position in enumerate(sorted({p["position"] for p in parts})):
        hotspot = checked(client.post(f"{BASE}/visual-pages/{scheme['id']}/hotspots", headers=headers,
            json={"position": position, "x": .05 + i * .04, "y": .1, "width": .02, "height": .02}), 201)
        checked(client.post(f"{BASE}/hotspots/{hotspot['id']}/verify", headers=headers,
            json={"expected_version": hotspot["version"]}))


def readiness(client, headers, revision):
    return checked(client.get(f"{BASE}/revisions/{revision['id']}/publication-readiness", headers=headers))


def test_5_zero_5_blocks_complete_readiness_and_direct_publish(client, auth_headers, session_factory, monkeypatch):
    revision, assembly, page, _ = setup_review(client, auth_headers, session_factory, 3)
    real = process.extract
    def one_empty(raw, operation, number, config):
        result = real(raw, operation, number, config)
        if operation == "page" and number == 3:
            result["rows"] = []
        return result
    monkeypatch.setattr(process, "extract", one_empty)
    previews = [extract(client, auth_headers, page, s) for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST"]
    assert [len(p["rows"]) for p in previews] == [5, 0, 5]
    for p in (previews[0], previews[2]):
        accept(client, auth_headers, page, p)
    mark(client, auth_headers, page)
    for source in resume(client, auth_headers, page)["sources"]:
        if source["source"]["page_number"] != 3:
            verify_http_source(client, auth_headers, source, manual=False)
    result = readiness(client, auth_headers, revision)
    assert not result["ready"]
    assert [e["visual_page_id"] for e in result["errors"] if e["code"] == "catalog_publication_source_review_required"] == [previews[1]["source"]["visual_page_id"]]
    listed = checked(client.get(f"{BASE}/assemblies/{assembly['id']}/reference-pages", headers=auth_headers))[0]
    assert listed["status"] == "NEEDS_ATTENTION"
    response = client.post(f"{BASE}/revisions/{revision['id']}/publish", headers=auth_headers, json={
        "expected_publication_digest": result["publication_digest"], "expected_current_published_revision_id": None, "confirmed": True})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "catalog_publication_not_ready"
    zero = resume(client, auth_headers, page)["sources"][1]
    original = client.get(f"{BASE}/visual-pages/{zero['visual_page_id']}/review-original", headers=auth_headers)
    for manual in (False, True):
        response = client.post(f"{BASE}/visual-pages/{zero['visual_page_id']}/review", headers=auth_headers, json={
            "expected_version": zero["version"], "fingerprint": zero["fingerprint"],
            "inspection_token": original.headers["X-Catalog-Review-Receipt"], "reason": "QA zero-page cannot be skipped", "manual_transcription": manual})
        assert response.status_code == 422
    # A retry with actual rows, explicit confirmation and review closes the gap.
    monkeypatch.setattr(process, "extract", real)
    accept(client, auth_headers, page, extract(client, auth_headers, page, {"id": zero["visual_page_id"]}))
    existing = {p["position"] for p in checked(client.get(f"{BASE}/reference-pages/{page['id']}/parts", headers=auth_headers))}
    assert len(existing) == 15
    for source in resume(client, auth_headers, page)["sources"]:
        verify_http_source(client, auth_headers, source, manual=False)
    assert not [e for e in readiness(client, auth_headers, revision)["errors"] if e["code"] == "catalog_publication_source_review_required"]


def test_resume_expired_preview_draft_edit_and_corrected_number_survive_drift(client, auth_headers, session_factory, monkeypatch):
    _, _, page, _ = setup_review(client, auth_headers, session_factory)
    source = next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST")
    preview = extract(client, auth_headers, page, source)
    row = preview["rows"][0]
    edited = {**row["payload"], "part_number": "QA-HUMAN-CORRECTED"}
    checked(client.patch(f"{BASE}/extraction-candidates/{row['candidate_id']}", headers=auth_headers, json={
        "expected_version": row["candidate_version"], "values": edited}))
    recovered = resume(client, auth_headers, page)["sources"][0]["preview"]
    assert recovered["rows"][0]["payload"]["part_number"] == "QA-HUMAN-CORRECTED"
    # Expiry affects a capability, never the persisted work.
    signed = service._sign({**service.json.loads(service.base64.urlsafe_b64decode(preview["token"].split('.')[0] + '==')),
        "created": int(service.time.time()) - 901})
    response = client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=auth_headers,
        json={"token": signed, "rows": [{"index": 0, "part": edited}], "confirm_warnings": True})
    assert response.status_code == 422
    accept(client, auth_headers, page, recovered)
    real = process.extract
    def drift(*args):
        result = real(*args)
        for row in result["rows"]:
            row["bbox"][0] += .01
        return result
    monkeypatch.setattr(process, "extract", drift)
    repeated = extract(client, auth_headers, page, source)
    result = accept(client, auth_headers, page, repeated)
    assert result["created_count"] == 0 and len(result["existing_part_ids"]) == 5
    persisted = checked(client.get(f"{BASE}/reference-pages/{page['id']}/parts", headers=auth_headers))
    assert len(persisted) == 5 and persisted[0]["part_number"] == "QA-HUMAN-CORRECTED"
    assert repeated["rows"][0]["candidate_id"] == row["candidate_id"]


def test_human_approval_invalidates_on_part_edit_and_stale_browser(client, auth_headers, session_factory):
    revision, _, page, _ = setup_review(client, auth_headers, session_factory)
    preview = extract(client, auth_headers, page, next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST"))
    accepted = accept(client, auth_headers, page, preview)
    mark(client, auth_headers, page)
    source = resume(client, auth_headers, page)["sources"][0]
    verified = verify_http_source(client, auth_headers, source, manual=False)
    assert verified["review_state"] == "VERIFIED"
    ready = readiness(client, auth_headers, revision)
    assert ready["ready"]
    checked(client.patch(f"{BASE}/parts/{accepted['part_ids'][0]}", headers=auth_headers,
        json={"part_number": "QA-OPERATOR-EDIT"}))
    stale = client.post(f"{BASE}/revisions/{revision['id']}/publish", headers=auth_headers, json={
        "expected_publication_digest": ready["publication_digest"], "expected_current_published_revision_id": None, "confirmed": True})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "catalog_publication_stale"
    assert not readiness(client, auth_headers, revision)["ready"]
    resumed = resume(client, auth_headers, page)["sources"][0]
    assert resumed["review_state"] == "NEEDS_REVIEW"
    verify_http_source(client, auth_headers, resumed, manual=False)
    with session_factory() as db:
        assert db.scalar(select(func.count(CatalogSourceReviewDecision.id))) == 2
    assert readiness(client, auth_headers, revision)["ready"]


def test_changed_ocr_number_is_conflict_and_not_silent_variant(client, auth_headers, session_factory, monkeypatch):
    _, _, page, _ = setup_review(client, auth_headers, session_factory)
    source = next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST")
    original = extract(client, auth_headers, page, source)
    accept(client, auth_headers, page, original)
    real = process.extract
    def changed(*args):
        result = copy.deepcopy(real(*args))
        result["rows"][0]["payload"]["part_number"] = "QA-OCR-CHANGED"
        return result
    monkeypatch.setattr(process, "extract", changed)
    altered = extract(client, auth_headers, page, source)
    assert altered["rows"][0]["candidate_state"] == "CONFLICT"
    response = client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=auth_headers,
        json={"token": altered["token"], "rows": [{"index": 0, "part": altered["rows"][0]["payload"]}], "confirm_warnings": True})
    assert response.status_code == 409
    assert len(checked(client.get(f"{BASE}/reference-pages/{page['id']}/parts", headers=auth_headers))) == 5


def test_interrupted_attempt_recovers_with_history_and_selection_edit_preserves_drafts(client, auth_headers, session_factory):
    _, _, page, artifact = setup_review(client, auth_headers, session_factory, 2)
    source = next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST")
    preview = extract(client, auth_headers, page, source)
    row = preview["rows"][0]
    checked(client.patch(f"{BASE}/extraction-candidates/{row['candidate_id']}", headers=auth_headers, json={
        "expected_version": row["candidate_version"], "values": {**row["payload"], "part_number": "QA-DRAFT-SAVED"}}))
    page = checked(client.patch(f"{BASE}/reference-pages/{page['id']}", headers=auth_headers,
        json={"expected_version": page["version"], "title": "QA revised selection"}))
    page = assign(client, auth_headers, page, artifact, [1], "SPARE_PARTS_LIST")
    resumed = resume(client, auth_headers, page)
    carried = next(s for s in resumed["sources"] if s["visual_page_id"] == source["id"])
    assert carried["preview"]["rows"][0]["payload"]["part_number"] == "QA-DRAFT-SAVED"
    assert carried["review_state"] != "VERIFIED"
    with session_factory() as db:
        state = db.get(ledger.Source, carried["id"])
        attempt = CatalogExtractionAttempt(source_id=state.id, state="RUNNING", extractor="QA", actor_id=1,
            deadline_at=utcnow() - timedelta(seconds=1))
        db.add(attempt)
        db.flush()
        state.current_attempt_id, state.processing_state = attempt.id, "RUNNING"
        db.commit()
    recovered = next(s for s in resume(client, auth_headers, page)["sources"] if s["id"] == carried["id"])
    assert recovered["processing_state"] == "CANCELLED"
    assert recovered["attempts"][-1]["state"] == "CANCELLED"
    assert recovered["candidates"][0]["values"]["part_number"] == "QA-DRAFT-SAVED"


def test_evidence_and_review_endpoints_reject_unauthorized_actors(client, auth_headers, viewer_headers, session_factory):
    _, assembly, page, _ = setup_review(client, auth_headers, session_factory)
    source = resume(client, auth_headers, page)["sources"][0]
    client.cookies.clear()
    for headers, status in (({}, 401), (viewer_headers, 403)):
        assert client.post(f"{BASE}/reference-pages/{page['id']}/review-session", headers=headers).status_code == status
        assert client.post(f"{BASE}/assemblies/{assembly['id']}/source-review", headers=headers).status_code == status
        assert client.get(f"{BASE}/visual-pages/{source['visual_page_id']}/review-original", headers=headers).status_code == status
        assert client.get(f"{BASE}/extraction-sources/{source['id']}/original", headers=headers).status_code == status
        assert client.post(f"{BASE}/visual-pages/{source['visual_page_id']}/review", headers=headers, json={
            "expected_version": 1, "fingerprint": "0" * 64, "inspection_token": "invalid", "reason": "QA invalid bypass attempt"}).status_code == status


def test_stale_confirm_cannot_discard_a_saved_draft_correction(client, auth_headers, session_factory):
    _, _, page, _ = setup_review(client, auth_headers, session_factory)
    preview = extract(client, auth_headers, page, next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST"))
    row = preview["rows"][0]
    edited = {**row["payload"], "part_number": "QA-PERSISTED-HUMAN"}
    checked(client.patch(f"{BASE}/extraction-candidates/{row['candidate_id']}", headers=auth_headers, json={
        "expected_version": 1, "values": edited}))
    for expected in (None, 1):
        payload = {"index": 0, "part": row["payload"]}
        if expected is not None:
            payload["expected_version"] = expected
        response = client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=auth_headers,
            json={"token": preview["token"], "rows": [payload], "confirm_warnings": True})
        assert response.status_code == 409
    assert resume(client, auth_headers, page)["sources"][0]["preview"]["rows"][0]["payload"] == edited


def test_processed_wrong_selection_requires_original_reason_and_retains_attempt_history(client, auth_headers, session_factory, monkeypatch):
    revision, _, page, artifact = setup_review(client, auth_headers, session_factory)
    page = assign(client, auth_headers, page, artifact, [1], "SPARE_PARTS_LIST")
    wrong = next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST" and s["page_number"] == 1)
    real = process.extract
    monkeypatch.setattr(process, "extract", lambda raw, operation, number, config:
        {"rows": [], "tables": [], "warnings": [], "method": "NATIVE", "ocr_used": False}
        if operation == "page" and number == 1 else real(raw, operation, number, config))
    extract(client, auth_headers, page, wrong)
    assert client.delete(f"{BASE}/visual-pages/{wrong['id']}", headers=auth_headers).status_code == 409
    state = next(s for s in resume(client, auth_headers, page)["sources"] if s["visual_page_id"] == wrong["id"])
    data = {"expected_version": state["version"], "fingerprint": state["fingerprint"],
        "inspection_token": "not-an-original-receipt", "reason": "QA scheme page selected as a parts list by mistake"}
    assert client.post(f"{BASE}/visual-pages/{wrong['id']}/selection-correction", headers=auth_headers, json=data).status_code == 422
    original = client.get(f"{BASE}/visual-pages/{wrong['id']}/review-original", headers=auth_headers)
    data["inspection_token"] = original.headers["X-Catalog-Review-Receipt"]
    assert client.post(f"{BASE}/visual-pages/{wrong['id']}/selection-correction", headers=auth_headers, json=data).status_code == 204
    current = resume(client, auth_headers, page)
    assert wrong["id"] not in {s["visual_page_id"] for s in current["sources"]}
    assert not readiness(client, auth_headers, revision)["ready"]
    with session_factory() as db:
        assert db.get(ledger.Source, state["id"]).source["page_number"] == 1
        assert len(list(db.scalars(select(CatalogExtractionAttempt).where(CatalogExtractionAttempt.source_id == state["id"])))) == 1
    # Even removing the now-unused draft document cannot erase ledger evidence.
    assignments = checked(client.get(f"{BASE}/assemblies/{page['assembly_id']}/reference-pages", headers=auth_headers))[0]["sources"]
    for assignment in assignments:
        assert client.delete(f"{BASE}/visual-pages/{assignment['id']}", headers=auth_headers).status_code == 204
    assert client.delete(f"{BASE}/artifacts/{artifact['id']}", headers=auth_headers).status_code == 204
    archived = client.get(f"{BASE}/extraction-sources/{state['id']}/original", headers=auth_headers)
    assert archived.status_code == 200 and archived.content == original.content
    assert archived.headers["Cache-Control"] == "private, no-store, max-age=0"
    assert "X-Catalog-Review-Receipt" not in archived.headers


def test_legacy_assembly_delete_cannot_bypass_processed_source_review(client, auth_headers, session_factory):
    from catalog_review_helpers import verify_http_revision
    from test_catalog_builder_parts import part, source, workspace
    _, revision_id, assembly_id, _ = workspace(client, auth_headers, session_factory, include_empty_group=False)
    _, spare_id, _, _ = source(client, auth_headers, assembly_id)
    created = checked(part(client, auth_headers, assembly_id), 201)
    assert client.post(f"{BASE}/parts/{created['id']}/source-pages", headers=auth_headers,
        json={"visual_page_ids": [spare_id]}).status_code == 201
    verify_http_revision(client, auth_headers, revision_id)
    response = client.delete(f"{BASE}/assemblies/{assembly_id}", headers=auth_headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "catalog_source_correction_review_required"
    assert client.get(f"{BASE}/assemblies/{assembly_id}/parts", headers=auth_headers).json()[0]["id"] == created["id"]
    state = checked(client.post(f"{BASE}/assemblies/{assembly_id}/source-review", headers=auth_headers))["sources"][0]
    assert state["review_state"] == "VERIFIED" and len(state["attempts"]) == 1


def test_owner_catalog_deletion_preserves_durable_review_history(client, auth_headers, session_factory):
    revision, _, page, _ = setup_review(client, auth_headers, session_factory)
    state = resume(client, auth_headers, page)
    catalog_id = revision["catalog_id"]
    path = f"/api/owner/data-deletion/catalog_definition/{catalog_id}"
    preview = checked(client.get(path + "/preview", headers=auth_headers))
    assert not preview["can_delete"]
    assert any(item["code"] == "catalog_extraction_sessions" for item in preview["blockers"])
    response = client.post(path + "/execute", headers=auth_headers, json={
        "current_password": os.environ["ADMIN_PASSWORD"], "confirmation_text": preview["confirmation_text"]})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "deletion_blocked"
    assert resume(client, auth_headers, page)["id"] == state["id"]


def test_zero_result_requires_explicit_complete_manual_transcription(client, auth_headers, session_factory, monkeypatch):
    _, _, page, _ = setup_review(client, auth_headers, session_factory)
    source = next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST")
    real = process.extract
    monkeypatch.setattr(process, "extract", lambda raw, operation, number, config:
        {"rows": [], "tables": [], "warnings": [], "method": "NATIVE", "ocr_used": False}
        if operation == "page" else real(raw, operation, number, config))
    extract(client, auth_headers, page, source)
    for position in range(1, 6):
        part = checked(client.post(f"{BASE}/reference-pages/{page['id']}/parts", headers=auth_headers, json={
            "position": str(position), "part_number": f"QA-{position}", "description": "QA component", "quantity": 2}), 201)
        checked(client.post(f"{BASE}/parts/{part['id']}/source-pages", headers=auth_headers,
            json={"visual_page_ids": [source["id"]]}), 201)
    state = resume(client, auth_headers, page)["sources"][0]
    original = client.get(f"{BASE}/visual-pages/{source['id']}/review-original", headers=auth_headers)
    data = {"expected_version": state["version"], "fingerprint": state["fingerprint"],
        "inspection_token": original.headers["X-Catalog-Review-Receipt"], "reason": "QA manually transcribed and checked all five original rows"}
    rejected = client.post(f"{BASE}/visual-pages/{source['id']}/review", headers=auth_headers, json=data)
    assert rejected.status_code == 422 and rejected.json()["detail"]["code"] == "catalog_source_review_manual_required"
    verified = checked(client.post(f"{BASE}/visual-pages/{source['id']}/review", headers=auth_headers,
        json={**data, "manual_transcription": True}))
    assert verified["review_state"] == "VERIFIED"
    assert len(verified["attempts"]) == 2
    assert verified["attempts"][-1]["kind"] == "MANUAL"


def test_remove_and_restore_mapping_never_revives_prior_approval(client, auth_headers, session_factory):
    revision, _, page, _ = setup_review(client, auth_headers, session_factory)
    visual = next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST")
    accepted = accept(client, auth_headers, page, extract(client, auth_headers, page, visual))
    mark(client, auth_headers, page)
    source = resume(client, auth_headers, page)["sources"][0]
    verified = verify_http_source(client, auth_headers, source, manual=False)
    assert readiness(client, auth_headers, revision)["ready"]
    maps = checked(client.get(f"{BASE}/parts/{accepted['part_ids'][0]}/source-pages", headers=auth_headers))
    assert client.delete(f"{BASE}/part-page-maps/{maps[0]['id']}", headers=auth_headers).status_code == 204
    checked(client.post(f"{BASE}/parts/{accepted['part_ids'][0]}/source-pages", headers=auth_headers,
        json={"visual_page_ids": [visual["id"]]}), 201)
    state = resume(client, auth_headers, page)["sources"][0]
    assert state["version"] > verified["version"] and state["review_state"] == "NEEDS_REVIEW"
    assert not readiness(client, auth_headers, revision)["ready"]
    with session_factory() as db:
        assert db.scalar(select(func.count(CatalogSourceReviewDecision.id))) == 1


def test_late_worker_result_cannot_cancel_a_newer_running_attempt(client, auth_headers, session_factory, monkeypatch):
    _, _, page, _ = setup_review(client, auth_headers, session_factory)
    visual = next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST")
    real = process.extract
    newer_id = None
    def superseded(*args):
        nonlocal newer_id
        evidence = real(*args)
        with session_factory() as db:
            source = db.scalar(select(ledger.Source))
            old = db.get(CatalogExtractionAttempt, source.current_attempt_id)
            old.state, old.finished_at = "CANCELLED", utcnow()
            new = CatalogExtractionAttempt(source_id=source.id, state="RUNNING", extractor="QA newer worker",
                actor_id=1, deadline_at=utcnow() + timedelta(minutes=1))
            db.add(new)
            db.flush()
            newer_id = new.id
            source.current_attempt_id, source.processing_state = new.id, "RUNNING"
            ledger.invalidate(source)
            db.commit()
        return evidence
    monkeypatch.setattr(process, "extract", superseded)
    response = client.post(f"{BASE}/reference-pages/{page['id']}/extract", headers=auth_headers,
        json={"visual_page_id": visual["id"]})
    assert response.status_code == 409
    with session_factory() as db:
        source = db.scalar(select(ledger.Source))
        assert source.current_attempt_id == newer_id and source.processing_state == "RUNNING"
        assert db.get(CatalogExtractionAttempt, newer_id).state == "RUNNING"


def test_reused_sqlite_part_id_does_not_rebind_an_accepted_candidate(client, auth_headers, session_factory):
    _, _, page, _ = setup_review(client, auth_headers, session_factory)
    visual = next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST")
    preview = extract(client, auth_headers, page, visual)
    accepted = accept(client, auth_headers, page, preview)
    removed_id = accepted["part_ids"][-1]
    assert client.delete(f"{BASE}/parts/{removed_id}", headers=auth_headers).status_code == 204
    replacement = checked(client.post(f"{BASE}/reference-pages/{page['id']}/parts", headers=auth_headers, json={
        "position": "5", "part_number": "QA-REPLACEMENT", "description": "QA manually replaced row"}), 201)
    assert replacement["id"] == removed_id  # SQLite's actual integer reuse, not a mocked identity.
    checked(client.post(f"{BASE}/parts/{removed_id}/source-pages", headers=auth_headers,
        json={"visual_page_ids": [visual["id"]]}), 201)
    resumed = resume(client, auth_headers, page)["sources"][0]
    assert resumed["preview"]["rows"][-1]["candidate_state"] == "CONFLICT"
    response = client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=auth_headers,
        json={"token": resumed["preview"]["token"], "rows": [{"index": 4, "part": preview["rows"][-1]["payload"]}], "confirm_warnings": True})
    assert response.status_code == 409
    assert len(checked(client.get(f"{BASE}/reference-pages/{page['id']}/parts", headers=auth_headers))) == 5
