"""Real HTTP publication gates, multiple catalogs and draft revision disposal."""

from app.models import AssetCategory, CatalogRevision, Machine
from catalog_review_helpers import verify_http_revision
from catalog_ux04_fixtures import workflow_pdf
from test_catalog_selected_extraction import BASE, checked, upload


def test_two_catalogs_late_binding_unbind_and_delete_rev2_preserve_published_access(client, auth_headers, session_factory):
    with session_factory() as db:
        category = AssetCategory(code="QA_UX04_RUNTIME", name_bg="QA", name_en="QA", name_ru="QA", capabilities=["HAS_PARTS_CATALOG"])
        db.add(category)
        db.flush()
        machines = [Machine(inventory_number=f"QA_UX04_RUNTIME_{index}", name="QA ONLY", category=category.code,
            category_id=category.id, brand="QA", model="QA") for index in range(2)]
        db.add_all(machines)
        db.commit()
        category_id, machine_ids = category.id, [row.id for row in machines]
    published, source_ids = [], []
    for number in range(2):
        item = checked(client.post(f"{BASE}/simple/catalogs", headers=auth_headers, json={
            "name": f"Synthetic QA runtime catalog {number}", "asset_category_id": category_id, "manufacturer": "QA", "model_reference": "QA"}), 201)
        revision = checked(client.get(f"{BASE}/catalogs/{item['id']}/revisions", headers=auth_headers))[0]
        assembly = checked(client.post(f"{BASE}/revisions/{revision['id']}/groups", headers=auth_headers, json={"name": "QA user assembly"}), 201)
        page = checked(client.post(f"{BASE}/assemblies/{assembly['id']}/reference-pages", headers=auth_headers, json={}), 201)
        artifact = checked(upload(client, auth_headers, revision, workflow_pdf()), 201)
        page = checked(client.post(f"{BASE}/reference-pages/{page['id']}/sources", headers=auth_headers, json={
            "artifact_id": artifact["id"], "expected_version": page["version"], "selections": [
                {"page_number": 4, "roles": ["EXPLODED_SCHEME"]}, {"page_number": 6, "roles": ["SPARE_PARTS_LIST"]}]}))
        scheme, source = page["sources"]
        preview = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extract", headers=auth_headers, json={"visual_page_id": source["id"]}))
        checked(client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=auth_headers,
            json={"token": preview["token"], "rows": [{"index": index, "part": row["payload"]} for index, row in enumerate(preview["rows"])], "confirm_warnings": True}))
        parts = checked(client.get(f"{BASE}/reference-pages/{page['id']}/parts", headers=auth_headers))
        kit = checked(client.post(f"{BASE}/assemblies/{assembly['id']}/repair-kits", headers=auth_headers,
            json={"code": f"QA_UX04_KIT_{number}", "name_bg": "QA ONLY", "source_visual_page_id": source["id"]}), 201)
        checked(client.post(f"{BASE}/repair-kits/{kit['id']}/components", headers=auth_headers,
            json={"part_id": parts[0]["id"], "quantity": 1}), 201)
        for position in ["1", "2"]:
            marker = checked(client.post(f"{BASE}/visual-pages/{scheme['id']}/hotspots", headers=auth_headers,
                json={"position": position, "x": .1, "y": .1, "width": .03, "height": .03}), 201)
            checked(client.post(f"{BASE}/hotspots/{marker['id']}/verify", headers=auth_headers, json={"expected_version": marker["version"]}))
        # No source review means even a complete diagram/table cannot publish.
        ready = checked(client.get(f"{BASE}/revisions/{revision['id']}/publication-readiness", headers=auth_headers))
        assert not ready["ready"]
        verify_http_revision(client, auth_headers, revision["id"])
        ready = checked(client.get(f"{BASE}/revisions/{revision['id']}/publication-readiness", headers=auth_headers))
        assert ready["ready"]
        checked(client.post(f"{BASE}/revisions/{revision['id']}/publish", headers=auth_headers, json={
            "expected_publication_digest": ready["publication_digest"], "expected_current_published_revision_id": None, "confirmed": True}))
        for machine_id in machine_ids:
            checked(client.post(f"{BASE}/catalogs/{item['id']}/assets/{machine_id}", headers=auth_headers), 201)
        published.append((item, revision))
    for machine_id in machine_ids:
        runtime = checked(client.get(f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers))
        assert len(runtime["catalogs"]) == len(runtime["assemblies"]) == 2
        parts_by_catalog = []
        for assembly in runtime["assemblies"]:
            sid = assembly["pages"][0]["source_id"]
            source_ids.append(sid)
            details = checked(client.get(f"/api/catalog/v2/assemblies/{sid}?machine_id={machine_id}", headers=auth_headers))
            assert len(details["parts"]) == 2
            parts_by_catalog.append({row["id"] for row in details["parts"]})
            # Request validation accepts a part from either active catalog.
            checked(client.post("/api/part-requests/multi", headers=auth_headers, json={"machine_id": machine_id,
                "lines": [{"catalog_part_id": details["parts"][0]["id"], "description": "Synthetic QA request", "quantity": 1}]}), 201)
        assert parts_by_catalog[0].isdisjoint(parts_by_catalog[1])
        assert len(checked(client.get(f"/api/catalog/v2/search?machine_id={machine_id}", headers=auth_headers))) == 4
        kits = checked(client.get(f"/api/catalog/v2/repair-kits?machine_id={machine_id}", headers=auth_headers))
        assert len(kits) == 2
        for kit in kits:
            checked(client.post("/api/part-requests/multi", headers=auth_headers, json={"machine_id": machine_id,
                "repair_kit_id": kit["id"], "repair_kit_mode": "KIT", "lines": [{"description": "Synthetic QA kit request", "quantity": 1}]}), 201)
    item, revision = published[0]
    catalog_status = client.patch(f"{BASE}/catalogs/{item['id']}", headers=auth_headers, json={"model_reference": "MISMATCH_Z9"}).status_code
    machine_status = client.patch(f"/api/machines/{machine_ids[0]}", headers=auth_headers, json={"model": "MISMATCH_Z9"}).status_code
    assert catalog_status == machine_status == 409
    draft = checked(client.post(f"{BASE}/catalogs/{item['id']}/edit", headers=auth_headers), 201)
    preview = checked(client.get(f"{BASE}/draft-deletion/revision/{draft['id']}", headers=auth_headers))
    assert not preview["blockers"]
    response = client.post(f"{BASE}/draft-deletion/revision/{draft['id']}", headers=auth_headers, json={"expected_digest": preview["digest"]})
    assert response.status_code == 204
    with session_factory() as db:
        assert db.get(CatalogRevision, draft["id"]) is None
        assert db.get(CatalogRevision, revision["id"]).status == "PUBLISHED"
    response = client.delete(f"{BASE}/catalogs/{item['id']}/assets/{machine_ids[0]}", headers=auth_headers)
    assert response.status_code == 204
    assert len(checked(client.get(f"/api/catalog/v2/machines/{machine_ids[0]}", headers=auth_headers))["catalogs"]) == 1
    assert len(checked(client.get(f"/api/catalog/v2/machines/{machine_ids[1]}", headers=auth_headers))["catalogs"]) == 2


def test_source_review_normal_click_needs_receipt_but_no_written_reason(client, auth_headers, session_factory):
    from test_catalog_durable_review import accept, extract, resume, setup_review
    _, _, page, _ = setup_review(client, auth_headers, session_factory)
    visual = next(source for source in page["sources"] if source["role"] == "SPARE_PARTS_LIST")
    accept(client, auth_headers, page, extract(client, auth_headers, page, visual))
    state = resume(client, auth_headers, page)["sources"][0]
    payload = {"expected_version": state["version"], "fingerprint": state["fingerprint"], "inspection_token": "uninspected"}
    assert client.post(f"{BASE}/visual-pages/{visual['id']}/review", headers=auth_headers, json=payload).status_code == 422
    original = client.get(f"{BASE}/visual-pages/{visual['id']}/review-original", headers=auth_headers)
    payload["inspection_token"] = original.headers["X-Catalog-Review-Receipt"]
    checked(client.post(f"{BASE}/visual-pages/{visual['id']}/review", headers=auth_headers, json=payload))
    assert resume(client, auth_headers, page)["sources"][0]["review_state"] == "VERIFIED"
    approved = resume(client, auth_headers, page)["sources"][0]
    candidate = approved["candidates"][0]
    changed = checked(client.patch(f"{BASE}/extraction-candidates/{candidate['id']}", headers=auth_headers,
        json={"expected_version": candidate["version"], "values": {"quantity": "3"}}))
    assert changed["state"] == "ACCEPTED" and changed["version"] > candidate["version"]
    current = resume(client, auth_headers, page)["sources"][0]
    assert current["review_state"] == "NEEDS_REVIEW"
    assert current["candidates"][0]["original"] == candidate["original"]
    parts = checked(client.get(f"{BASE}/reference-pages/{page['id']}/parts", headers=auth_headers))
    assert float(next(part for part in parts if part["id"] == candidate["part_id"])["quantity"]) == 3
    assert client.patch(f"{BASE}/extraction-candidates/{candidate['id']}", headers=auth_headers,
        json={"expected_version": candidate["version"], "values": {"quantity": "9"}}).status_code == 409
    checked(client.patch(f"{BASE}/parts/{candidate['part_id']}", headers=auth_headers, json={"quantity": "4"}))
    assert client.patch(f"{BASE}/extraction-candidates/{candidate['id']}", headers=auth_headers,
        json={"expected_version": changed["version"], "values": {"quantity": "9"}}).status_code == 409
