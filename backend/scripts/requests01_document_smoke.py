"""Render multi-page FREE_FORM DOCX through the application's container converter.

Explicit QA content only; no database connection, official registration or source edit.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import fitz

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.documents.request_issue_documents import build_docx  # noqa: E402
from app.template_engine import convert_docx_to_pdf  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    target = parser.parse_args().output
    target.mkdir(parents=True, exist_ok=True)
    report = []
    for language in ("bg", "en", "ru"):
        data = {
            "request_kind": "FREE_FORM",
            "language": language,
            "official_number": "KK1000",
            "approved_at": datetime.now(UTC).isoformat(),
            "approved_by_name": "QA approver",
            "requested_by_name": "QA requester",
            "department": "QA layout check",
            "reason": "QA example only; no official document is registered.",
            "lines": [
                {
                    "description": f"QA ROW {index:03d} Кирилица " + "дълго описание " * 20,
                    "quantity": "0.75",
                    "unit": "kg",
                }
                for index in range(1, 49)
            ],
        }
        source = BACKEND / "resources/templates" / f"part_request-{language}-v3.docx"
        docx = build_docx(data, source.read_bytes())
        pdf = convert_docx_to_pdf(docx)
        if pdf is None:
            raise RuntimeError("requests01_docx_conversion_unavailable")
        (target / f"free-form-{language}.docx").write_bytes(docx)
        (target / f"free-form-{language}.pdf").write_bytes(pdf)
        with fitz.open(stream=pdf, filetype="pdf") as document:
            assert len(document) > 1
            content = "\n".join(page.get_text() for page in document)
            assert sorted(re.findall(r"QA ROW (\d{3})", content)) == [
                f"{i:03d}" for i in range(1, 49)
            ]
            assert "Кирилица" in content and "KK1000" in content
            amount = "0.75" if language == "en" else "0,75"
            assert content.count(amount) == 48
            for index, page in enumerate(document, 1):
                if "QA ROW" in page.get_text():
                    assert "DESCRIPTION" in page.get_text() and "Q'TY ordered" in page.get_text()
                for rectangle in page.search_for(amount):
                    assert rectangle.x0 > page.rect.width * 0.7
                    assert page.rect.contains(rectangle)
                for block in page.get_text("blocks"):
                    assert page.rect.contains(fitz.Rect(block[:4]))
                page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25)).save(
                    target / f"{language}-page-{index}.png"
                )
            report.append(
                {
                    "language": language,
                    "pages": len(document),
                    "rows": 48,
                    "repeated_headers": True,
                    "quantities_unclipped": True,
                }
            )
    (target / "proof.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("REQUESTS01_DOCX_LAYOUT_PASSED_BG_EN_RU")


if __name__ == "__main__":
    main()
