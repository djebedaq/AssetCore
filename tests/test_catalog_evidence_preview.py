"""Original geometry is additive, actor-bound evidence, never a UI guess."""
import base64
import json

from app.catalog_admin.parts_extraction import process
from test_catalog_durable_review import extract, resume, setup_review
from test_catalog_selected_extraction import BASE


def test_preview_and_resume_keep_exact_original_geometry(client, auth_headers, session_factory):
    _, _, page, _ = setup_review(client, auth_headers, session_factory)
    source = next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST")
    preview = extract(client, auth_headers, page, source)
    geometry = preview["page_geometry"]
    assert geometry["width"] > 0 and geometry["height"] > 0
    assert geometry["rotation_matrix"] == [1, 0, 0, 1, 0, 0]
    encoded = preview["token"].split(".")[0]
    claim = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    assert claim["page_geometry"] == geometry
    assert claim["source"] == preview["source"]
    restored = resume(client, auth_headers, page)["sources"][0]["preview"]
    assert restored["page_geometry"] == geometry
    assert restored["source"] == preview["source"]
    claim["page_geometry"]["width"] += 100
    forged = base64.urlsafe_b64encode(json.dumps(claim).encode()).decode().rstrip("=") + "." + preview["token"].split(".")[1]
    rejected = client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=auth_headers,
        json={"token": forged, "confirm_warnings": True, "rows": [{"index": 0, "part": preview["rows"][0]["payload"]}]})
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "catalog_extraction_token_invalid"
    assert client.get(f"{BASE}/reference-pages/{page['id']}/parts", headers=auth_headers).json() == []


def test_legacy_evidence_without_geometry_does_not_invent_coordinates(client, auth_headers, session_factory, monkeypatch):
    _, _, page, _ = setup_review(client, auth_headers, session_factory)
    source = next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST")
    real = process.extract

    def legacy(raw, operation, number, config):
        result = real(raw, operation, number, config)
        for key in ("width", "height", "rotation_matrix"):
            result.pop(key, None)
        return result

    monkeypatch.setattr(process, "extract", legacy)
    assert extract(client, auth_headers, page, source)["page_geometry"] == {}
