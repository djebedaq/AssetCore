from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from sqlalchemy import select

from app.models import Machine, PartCatalog, TechnicalDocument


def test_verified_catalog_is_imported_with_exact_source_traceability(session_factory):
    with session_factory() as session:
        parts = list(session.scalars(select(PartCatalog)))
        assert len(parts) == 774
        assert Counter(part.brand for part in parts) == {
            "Falch": 495,
            "CombiJet": 262,
            "HYDWIN (Fussen)": 17,
        }
        assert all(part.is_verified for part in parts)
        assert all(part.verification_status == "VERIFIED_SOURCE_TABLE" for part in parts)
        assert all(part.source_document and part.source_page for part in parts)
        assert all(part.source_document_sha256 and len(part.source_document_sha256) == 64 for part in parts)
        assert all(part.compatible_machine_numbers for part in parts)

        hydwin = session.scalar(
            select(PartCatalog).where(PartCatalog.part_number == "7.908-007")
        )
        assert hydwin is not None
        assert hydwin.model == "FCE15/50"
        assert hydwin.quantity == 1.0
        assert hydwin.estimated_price == 95.07
        assert hydwin.currency == "USD"
        assert hydwin.compatible_machine_numbers == ["20", "21", "22", "23", "24"]

        decimal_quantity = session.scalar(
            select(PartCatalog).where(
                PartCatalog.brand == "Falch",
                PartCatalog.part_number == "S717",
            )
        )
        assert decimal_quantity is not None
        assert decimal_quantity.quantity == 0.35

        combijet = session.scalar(
            select(PartCatalog).where(
                PartCatalog.brand == "CombiJet",
                PartCatalog.part_number == "CJL30949",
                PartCatalog.assembly == "Chassis",
            )
        )
        assert combijet is not None
        assert combijet.source_page == 29
        assert combijet.diagram_page == 28
        assert combijet.source_version == "JE60-500 User & Parts Manual V4.8"


def test_catalog_machine_filter_returns_only_compatible_verified_parts(
    client, auth_headers, session_factory
):
    with session_factory() as session:
        machine_ids = {
            item.inventory_number: item.id
            for item in session.scalars(select(Machine))
        }

    cases = {
        "4": (262, "CombiJet", "JE60-500"),
        "7": (229, "Falch", "Wheel Jet 30-e"),
        "9": (266, "Falch", "Wheel Jet 15-e"),
        "19": (266, "Falch", "Wheel Jet 15-e"),
        "20": (17, "HYDWIN (Fussen)", "FCE15/50"),
    }
    for machine_number, (expected_count, expected_brand, expected_model) in cases.items():
        response = client.get(
            f"/api/catalog/parts?verified_only=true&machine_id={machine_ids[machine_number]}",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert len(payload) == expected_count
        assert {item["brand"] for item in payload} == {expected_brand}
        assert {item["model"] for item in payload} == {expected_model}
        assert all(machine_number in item["compatible_machine_numbers"] for item in payload)


def test_catalog_manifest_hashes_match_bundled_manuals(session_factory):
    root = Path(__file__).resolve().parents[1] / "backend" / "resources" / "technical_docs"
    with session_factory() as session:
        by_source: dict[str, str] = {}
        for part in session.scalars(select(PartCatalog)):
            by_source.setdefault(part.source_document, part.source_document_sha256)
            assert by_source[part.source_document] == part.source_document_sha256
        for relative, expected in by_source.items():
            source = root / relative
            assert source.is_file()
            assert hashlib.sha256(source.read_bytes()).hexdigest() == expected

        quote = session.scalar(
            select(TechnicalDocument).where(
                TechnicalDocument.file_path == "falch1000/offer_sq-de103869_2025-10-22.pdf"
            )
        )
        assert quote is not None
        assert "Commercial quotation" in (quote.notes or "")


def test_visual_catalog_document_context_and_page_preview(client, auth_headers, session_factory):
    with session_factory() as session:
        document = session.scalar(
            select(TechnicalDocument).where(
                TechnicalDocument.file_path == "combijet/JE60-500_manual.pdf"
            )
        )
        assert document is not None
        document_id = document.id

    library = client.get(
        "/api/technical-library?brand=CombiJet&model=JE60-500",
        headers=auth_headers,
    )
    assert library.status_code == 200, library.text
    payload = next(item for item in library.json() if item["id"] == document_id)
    assert payload["source_key"] == "combijet/JE60-500_manual.pdf"
    assert payload["page_preview_endpoint"].endswith("/pages/{page_number}/preview")

    preview = client.get(
        f"/api/technical-library/{document_id}/pages/28/preview?scale=1",
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    assert preview.headers["content-type"].startswith("image/png")
    assert preview.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert preview.headers["x-document-sha256"] == payload["sha256"]
    assert int(preview.headers["x-document-page-count"]) >= 28
    assert preview.headers["etag"]

    missing = client.get(
        f"/api/technical-library/{document_id}/pages/9999/preview",
        headers=auth_headers,
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "technical_document_page_not_found"


def test_visual_catalog_frontend_is_machine_first_and_does_not_fake_hotspots():
    source = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "src"
        / "IndustrialPlatform.tsx"
    ).read_text(encoding="utf-8")
    assert "catalog.chooseMachinePlaceholder" in source
    assert "machine_id=${selectedMachineId}" in source
    assert "CatalogAssemblyBrowser" in source
    assert "/pages/${pageNumber}/preview?scale=2" in source
    assert "hotspots.filter((item) => item.is_verified)" in source
    assert "catalog.noVerifiedDiagram" in source
    assert "catalog.tableSelectionFallback" in source
    assert "selected-catalog-row" in source
