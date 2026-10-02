"""Selected-list native/OCR extraction and binary PDF upload regressions."""

import fitz
import pytest
from app.catalog_admin.parts_extraction import extraction
from app.catalog_admin.parts_extraction.process import configuration
from app.models import AssetCategory
from app.settings import settings
from catalog_extraction_fixtures import cyrillic_manual, encrypted, manual, over_12_mib, scanned

BASE = "/api/admin/catalog-builder"


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
    checked(client.post(f"{BASE}/revisions/{revision['id']}/groups", headers=headers, json={"name": "QA reference"}), 201)
    return catalog, revision



def upload(client, headers, revision, content):
    return client.post(f"{BASE}/revisions/{revision['id']}/pdf", headers=headers,
                       files={"file": ("qa.pdf", content, "application/octet-stream")})



@pytest.mark.parametrize("options", [dict(), {"language": "de"}, {"landscape": True}, {"rotated": True},
    {"both": True}, {"groups": 3}, {"multipage": True}, {"wrapped": True}, {"repeated": True}, {"missing": True}])
def test_generic_native_layout_cases(options):
    with fitz.open(stream=manual(**options), filetype="pdf") as pdf:
        pages = [extraction.extract_page(page, configuration(settings)) for page in pdf]
    rows = [row for page in pages for row in page["rows"]]
    assert rows and {row["payload"]["position"] for row in rows} == {"1", "13A", "13.1", "A12"}
    assert all(row["payload"]["part_number"].startswith("QA-") for row in rows)
    assert all(not page["ocr_used"] for page in pages)
    if options.get("wrapped"):
        assert all("continued description" in row["payload"]["description"] for row in rows)
    if options.get("rotated"):
        assert pages[0]["rotation"] == 90



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
        assert "OCR_DISABLED" in scan["warnings"]
        assert native["rows"] and "OCR_DISABLED" not in native["warnings"]
        def unavailable(*args, **kwargs):
            raise RuntimeError("QA unavailable")
        monkeypatch.setattr(fitz.Page, "get_textpage_ocr", unavailable)
        result = extraction.extract_page(pdf[0], configuration(settings))
        assert "OCR_UNAVAILABLE" in result["warnings"] and not result["ocr_used"]



@pytest.mark.parametrize("language", ["bg", "ru"])
def test_cyrillic_native_bom(language):
    with fitz.open(stream=cyrillic_manual(language), filetype="pdf") as pdf:
        page = extraction.extract_page(pdf[0], configuration(settings))
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
