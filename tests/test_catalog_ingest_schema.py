"""Unknown-OEM schemas and permanent Item/No context regressions."""

import fitz
import pytest
from app.catalog_admin.ingest import extraction
from app.catalog_admin.ingest.association import relationship
from app.catalog_admin.ingest.process import configuration
from app.catalog_admin.ingest.schema import (
    column_profile,
    field_name,
    header_candidates,
    infer_schema,
    role_score,
)
from app.settings import settings
from catalog_ingest_fixtures import contextual_table, manual

HEADERS = [
    ["No.", "Part No.", "Item", "Qty"],
    ["No.", "Part No.", "Item", "Qty", "Remark"],
    ["Item", "Part No.", "Description", "Qty"],
    ["Pos", "Art. Nr.", "Benennung", "Menge"],
    ["Ref.", "Part Number", "Designation", "Quantity"],
    ["Index", "Stock Code", "Part Name", "Pieces"],
]


def analyze(data, **config):
    with fitz.open(stream=data, filetype="pdf") as pdf:
        return extraction.extract_page(pdf[0], {**configuration(settings), "ocr_enabled": False, **config})


@pytest.mark.parametrize("headers", HEADERS)
@pytest.mark.parametrize("ruled", [False, True])
def test_contextual_headers_extract_rows_including_item_as_description(headers, ruled):
    rows = [["13A", "QA-101", "Seal", "2.5"], ["2", "QA-102", "Bolt M8, DIN (20 mm)", "1200"]]
    if len(headers) == 5:
        rows = [row + ["See next page"] for row in rows]
    page = analyze(contextual_table(headers, rows, ruled=ruled))
    assert page["role"] == "SPARE_PARTS_LIST"
    assert len(page["rows"]) == 2  # The original zero-row regression.
    assert [row["payload"]["position"] for row in page["rows"]] == ["13A", "2"]
    assert page["rows"][0]["payload"]["description"] == "Seal"
    assert page["rows"][1]["payload"]["quantity"] == "1200"
    assert page["rows"][0]["raw_cells"][:3] == rows[0][:3]
    assert page["rows"][0]["schema"]["mapping"]["2"] == "description"
    assert not page["labels"]
    if len(headers) == 5:
        assert page["rows"][0]["payload"]["technical_notes"] == "See next page"


def test_profiles_and_role_candidates_do_not_assign_item_globally():
    assert field_name("Item") is None
    assert set(header_candidates("ITEM")) == {"position", "description"}
    description = column_profile(["Seal", "Pump", "Bolt M8, DIN (20 mm)"])
    assert description["description"] == 1 and description["position"] == 0
    assert role_score("Item", description, "description") > role_score("Item", description, "position")
    assert column_profile(["99", "13A", "2", "13.1", "A12"])["position"] == 1
    assert column_profile(["1200", "2,5", "0.5"])["quantity"] == 1
    assert header_candidates("Bemerkungen") == {"technical_notes": 2.5}


def test_ambiguous_headers_resolve_from_values_but_equal_id_columns_stay_uncertain():
    resolved = infer_schema(["ID", "Number", "Type", "Qty"], [["1", "QA-123", "Seal", "2"], ["4", "QA-124", "Pump", "1"]])
    assert resolved["state"] == "RESOLVED" and resolved["mapping"]["0"] == "position"
    headers = ["ID", "Number", "Type", "Qty"]
    rows = [["1", "51", "Seal", "2"], ["4", "54", "Pump", "1"]]
    ambiguous = infer_schema(headers, rows)
    assert ambiguous["state"] == "NEEDS_REVIEW"
    assert ambiguous["margin"] == 0 and len(ambiguous["alternatives"]) >= 2
    page = analyze(contextual_table(headers, rows, ruled=True))
    assert page["tables"] and not page["rows"] and not page["labels"]
    assert page["role"] == "SPARE_PARTS_LIST" and page["confidence"] < .9
    assert "SCHEMA_AMBIGUOUS" in page["warnings"]
    assert page["tables"][0]["sample_cells"] == rows


@pytest.mark.parametrize("ruled", [False, True])
def test_unresolved_optional_column_and_malformed_unknown_schema_keep_geometry(ruled):
    headers = HEADERS[0] + ["Finish"]
    page = analyze(contextual_table(headers, [["1", "QA-1", "Seal", "1", "Black"]]))
    assert len(page["rows"]) == 1 and page["role"] == "SPARE_PARTS_LIST"
    assert "UNKNOWN_COLUMN" in page["rows"][0]["warnings"]
    page = analyze(contextual_table(["X", "Y", "Z", "Q"], [["1", "51", "61", "2"], ["4", "54", "64", "1"]], ruled=ruled))
    assert page["role"] == "AMBIGUOUS" and page["tables"] and not page["labels"]
    assert infer_schema([""], [["a"]])["state"] == "NEEDS_REVIEW"


@pytest.mark.parametrize("number", ["", "/", "-"])
def test_partial_rows_repeated_positions_and_unknown_quantity_are_retained(number):
    rows = [["9", number, "Seal", "?"], ["2", "QA-102", "Pump", "1"], ["2", "QA-103", "Valve", "1"]]
    page = analyze(contextual_table(rows=rows))
    assert len(page["rows"]) == 3
    first = page["rows"][0]
    assert first["payload"]["part_number"] == number
    assert "MISSING_PART_NUMBER" in first["warnings"] and "QUANTITY_UNCERTAIN" in first["warnings"]
    assert first["payload"]["quantity_raw"] == "?" and first["payload"]["quantity"] is None


@pytest.mark.parametrize("repeat_header", [True, False])
def test_continuation_geometry_and_profiles_preserve_source_without_heading(repeat_header):
    with fitz.open(stream=contextual_table(continuation=True, repeat_header=repeat_header), filetype="pdf") as pdf:
        first = extraction.extract_page(pdf[0], configuration(settings))
        second = extraction.extract_page(pdf[1], {**configuration(settings), "previous_heading": first["heading"],
            "continuation_tables": first["tables"]})
    assert len(second["rows"]) == 2 and second["heading"] is None
    assert relationship(first, second) == "TABLE_CONTINUATION"
    unrelated = {**second, "heading": "QA OTHER UNIT"}
    assert relationship(first, unrelated) is None


def test_both_uses_only_labels_outside_table():
    page = analyze(contextual_table(both=True))
    assert page["role"] == "BOTH" and len(page["rows"]) == 2
    assert {label["text"] for label in page["labels"]} == {"13A", "2"}
    assert all(label["bbox"][1] < page["tables"][0]["bbox"][1] for label in page["labels"])


def test_impossible_mapping_retries_and_search_is_bounded():
    schema = infer_schema(["Item", "Part No.", "No.", "Qty"], [["Seal", "QA-01", "3", "2"], ["Pump", "QA-02", "7", "1"]])
    assert schema["state"] == "RESOLVED" and schema["mapping"]["2"] == "position"
    assert len(schema["alternatives"]) <= 5
    assert infer_schema(["Code"] * 13, [["1"] * 13])["state"] == "NEEDS_REVIEW"


def test_section_and_subtotal_rows_do_not_create_parts_and_legacy_row_text_stays_stable():
    page = analyze(contextual_table(rows=[["", "", "Repair kit components", ""],
        ["1", "QA-1", "Seal", "1"], ["Total", "", "", "5"], ["", "", "See note 1", ""]]))
    assert len(page["rows"]) == 1 and page["rows"][0]["payload"]["position"] == "1"
    with fitz.open(stream=manual(), filetype="pdf") as pdf:
        row = extraction.extract_page(pdf[1], configuration(settings))["rows"][0]
    assert row["raw_text"] == "1 QA-0-0 QA component 2.5"  # Original CATALOG_INGEST_1 identity input.


@pytest.mark.parametrize("ruled", [False, True])
def test_version_date_page_footer_is_retained_as_metadata_instead_of_a_fake_part(ruled):
    page = analyze(contextual_table(rows=[["1", "QA-1", "Seal", "1"],
        ["V1.0", "30/10/2025", "", "11"]], ruled=ruled))
    assert [row["payload"]["position"] for row in page["rows"]] == ["1"]
    assert page["tables"][0]["excluded_rows"][0]["raw_cells"] == ["V1.0", "30/10/2025", "", "11"]
    assert page["tables"][0]["excluded_rows"][0]["bbox"]
    # Version-like genuine position plus an actual part/description is preserved.
    genuine = analyze(contextual_table(rows=[["1", "QA-1", "Seal", "1"], ["V1.0", "QA-2", "Valve", "2"]]))
    assert len(genuine["rows"]) == 2
