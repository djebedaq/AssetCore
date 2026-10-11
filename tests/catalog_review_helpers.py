"""Explicit operator review for positive synthetic publication fixtures only."""
from app.catalog_admin.parts_extraction import review
from app.catalog_admin.parts_extraction.schemas import SourceReview

BASE = "/api/admin/catalog-builder"
REASON = "QA operator compared every synthetic part with the exact original source."


def verify_http_source(client, headers, source, *, manual=True):
    response = client.get(f"{BASE}/visual-pages/{source['visual_page_id']}/review-original", headers=headers)
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")
    response = client.post(f"{BASE}/visual-pages/{source['visual_page_id']}/review", headers=headers, json={
        "expected_version": source["version"], "fingerprint": source["fingerprint"],
        "inspection_token": response.headers["X-Catalog-Review-Receipt"], "reason": REASON,
        "manual_transcription": manual})
    assert response.status_code == 200, response.json().get("detail") if response.status_code != 200 else None
    return response.json()


def verify_http_revision(client, headers, revision_id):
    assemblies = client.get(f"{BASE}/revisions/{revision_id}/assemblies", headers=headers).json()
    for assembly in assemblies:
        pages = client.get(f"{BASE}/assemblies/{assembly['id']}/reference-pages", headers=headers).json()
        paths = [f"{BASE}/assemblies/{assembly['id']}/source-review"] + [
            f"{BASE}/reference-pages/{page['id']}/review-session" for page in pages]
        for path in paths:
            response = client.post(path, headers=headers)
            assert response.status_code == 200
            for source in response.json()["sources"]:
                verify_http_source(client, headers, source)


def verify_service_sources(db, actor, assembly_id, reference_page_id=None):
    workspace = review.workspace(db, actor, assembly_id, reference_page_id)
    for item in workspace["sources"]:
        image, receipt = review.original(db, actor, item["visual_page_id"])
        assert image.startswith(b"\x89PNG")
        review.verify(db, actor, item["visual_page_id"], SourceReview(
            expected_version=item["version"], fingerprint=item["fingerprint"], inspection_token=receipt,
            reason=REASON, manual_transcription=True))
