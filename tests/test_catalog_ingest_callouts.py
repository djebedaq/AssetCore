"""Combined callouts stay uncertain and cannot fabricate BOM members."""

import fitz
import pytest
from app.catalog_admin.ingest.extraction import ROLE_WORDS, extract_page
from app.catalog_admin.ingest.geometry import match_position
from app.catalog_admin.ingest.headings import select_heading
from app.catalog_admin.ingest.labels import label_members
from app.catalog_admin.ingest.process import configuration
from app.settings import settings
from catalog_ingest_fixtures import contextual_table


@pytest.mark.parametrize("text,members", [("7,8", ["7", "8"]), ("33-35", ["33", "34", "35"]),
    ("13A;13.1", ["13A", "13.1"]), ("A12", ["A12"]), ("1-500", None), ("9-1", None),
    ("7,part-number", None), ("13 mm", None)])
def test_bounded_combined_label_members(text, members):
    assert label_members(text) == members


@pytest.mark.parametrize("callout", ["33-35", "33 - 35"])
def test_combined_labels_are_native_source_candidates_only_when_every_member_exists(callout):
    with fitz.open(stream=contextual_table(both=True), filetype="pdf") as pdf:
        pdf[0].insert_text((150, 150), callout)
        layout = extract_page(pdf[0], configuration(settings))
    assert len(layout["rows"]) == 2  # Never add rows 33, 34, 35 to the BOM.
    result = match_position("34", [(1, layout)], {"33", "34", "35"})
    assert result["match"] == "LOW_CONFIDENCE" and result["combined"]
    assert result["locations"][0]["raw_text"] == callout
    assert result["locations"][0]["bbox"] == next(w["bbox"] for w in layout["labels"] if w["text"] == callout)
    assert match_position("34", [(1, layout)], {"33", "34"})["match"] == "NOT_FOUND"
    assert match_position("34", [(1, layout)])["match"] == "NOT_FOUND"
    duplicated = {**layout, "labels": layout["labels"] * 2}
    assert match_position("34", [(1, duplicated)], {"33", "34", "35"})["match"] == "MULTIPLE_CANDIDATES"


def test_running_parent_header_does_not_hide_smaller_nested_source_title():
    candidates = [{"text": "QA PARENT", "bbox": [480, 25, 555, 36], "size": 11},
                  {"text": "QA NESTED UNIT", "bbox": [230, 50, 360, 60], "size": 10}]
    name, evidence = select_heading(candidates, 595, 842, ROLE_WORDS)
    assert name == "QA NESTED UNIT" and evidence["running_header"]["text"] == "QA PARENT"
    assert evidence["inferred"] and evidence["method"] == "NESTED_TITLE"
    # Normal centered hierarchy retains its strongest title, without inventing a child.
    candidates[0]["bbox"] = [200, 25, 380, 36]
    assert select_heading(candidates, 595, 842, ROLE_WORDS)[0] == "QA PARENT"
    candidates.insert(0, {"text": "QA OCR ARTIFACT", "bbox": [200, 10, 380, 30], "size": 25, "method": "OCR"})
    assert select_heading(candidates, 595, 842, ROLE_WORDS)[0] == "QA PARENT"
