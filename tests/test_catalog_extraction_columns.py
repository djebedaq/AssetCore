"""Geometry regressions reach actual table detection AND semantic BOM output."""

import fitz
import pytest
from app.catalog_admin.parts_extraction.columns import assign_words, header_geometry, infer_columns
from app.catalog_admin.parts_extraction.extraction import extract_page
from app.catalog_admin.parts_extraction.process import configuration
from app.settings import settings
from catalog_extraction_fixtures import centered_geometry


@pytest.mark.parametrize("options", [{}, {"width": 595}, {"width": 950}, {"shifted": 25},
    {"noisy": True}, {"notes": True}, {"wrapped": True}, {"multiple": True},
    {"width": 842}, {"width": 680}, {"width": 1100}, {"shifted": -10},
    {"notes": True, "wrapped": True}, {"notes": True, "noisy": True},
    {"wrapped": True, "noisy": True}, {"width": 950, "wrapped": True},
    {"width": 842, "notes": True}, {"width": 950, "shifted": 25},
    {"width": 680, "noisy": True}, {"width": 1100, "notes": True}])
def test_centered_headers_left_values_reconstruct_exact_cells_and_semantics(options):
    with fitz.open(stream=centered_geometry(**options), filetype="pdf") as pdf:
        result = extract_page(pdf[0], {**configuration(settings), "ocr_enabled": False})
    assert result["tables"]
    assert len(result["rows"]) == (6 if options.get("multiple") else 3)
    first = result["rows"][0]
    assert first["raw_cells"][:4] == ["1", "QA-123456", "Hex Head Bolt", "4"]
    assert first["payload"] == {"position": "1", "part_number": "QA-123456",
        "description": "Hex Head Bolt" + ("\ncontinued source description" if options.get("wrapped") else ""),
        "quantity": "4", "quantity_raw": "4"}
    assert not first["warnings"] and first["confidence"] >= .9
    header = result["tables"][0]["header_geometry"][1]
    number = next(w for w in result["tables"][0]["sample_assignments"][0] if w["text"] == "QA-123456")
    assert number["bbox"][0] < header["x0"] - 10
    assert number["column"] == 1
    assert "Outside" not in str(result["tables"])
    assert result["rows"][1]["payload"]["quantity"] == "1200"
    bounds = result["tables"][0]["geometry"]["boundaries"]
    assert bounds == sorted(bounds) and bounds[0] > 0 and bounds[-1] < result["width"]


def test_headerless_continuation_scales_normalized_regions_to_changed_page_width():
    with fitz.open(stream=centered_geometry(continuation=True, second_width=950), filetype="pdf") as pdf:
        first = extract_page(pdf[0], configuration(settings))
        second = extract_page(pdf[1], {**configuration(settings), "continuation_tables": first["tables"]})
    assert len(second["rows"]) == 3
    assert second["tables"][0]["geometry"]["normalized_boundaries"] == pytest.approx(first["tables"][0]["geometry"]["normalized_boundaries"])
    assert "CONTINUATION_INFERRED" in second["rows"][0]["warnings"]
    assert second["rows"][0]["payload"]["part_number"] == "QA-123456"


def test_overlapping_word_preserves_assignment_and_requires_review():
    words = [{"text": "QA-overlap", "bbox": [90, 20, 110, 30]}]
    cells, assignments, conflicts = assign_words(words, [0, 100, 200])
    assert conflicts == 1 and assignments[0]["conflict"]
    assert "QA-overlap" in cells
    headers = [header_geometry(str(index), [{"text": str(index), "bbox": [x, 0, x + 10, 10]}]) for index, x in enumerate([10, 80, 150])]
    geometry = infer_columns(headers, [words, words], 0, 200, 200)
    assert geometry["state"] == "NEEDS_REVIEW" and geometry["alternatives"]


def test_metadata_line_and_disconnected_sidebar_do_not_prove_repeated_table_rows():
    with fitz.open() as pdf:
        page = pdf.new_page(width=850, height=650)
        for x, text in [(40, "Product"), (100, "Name:"), (160, "Technical machine manual"), (620, "QA Organization")]:
            page.insert_text((x, 100), text)
        page.insert_text((620, 125), "Contact: QA")
        for x, text in [(40, "Product"), (100, "Model:"), (190, "QA12")]:
            page.insert_text((x, 145), text)
        result = extract_page(page, configuration(settings))
    assert not result["rows"]
