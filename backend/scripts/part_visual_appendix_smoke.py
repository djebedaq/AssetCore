"""Verify the final official appendix DOCX survives real LibreOffice conversion."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import fitz
from app.documents import part_request_documents
from document_qa import generate


def main() -> None:
    converted: list[tuple[bytes, bytes | None]] = []
    original = part_request_documents.convert_docx_to_pdf

    def observe(docx: bytes) -> bytes | None:
        pdf = original(docx)
        converted.append((docx, pdf))
        return pdf

    part_request_documents.convert_docx_to_pdf = observe
    try:
        with tempfile.TemporaryDirectory(prefix="assetcore-visual-qa-") as directory:
            result = generate(Path(directory))
            if len(converted) != 1 or result["part_request"]["visual_appendix"]["rendered_images"] != 1:
                raise RuntimeError("Isolated document QA failed.")
            docx, pdf = converted[0]
            if pdf is None:
                raise RuntimeError("LibreOffice did not convert the final appendix DOCX.")
            if hashlib.sha256(docx).hexdigest() != result["part_request"]["docx"]["sha256"]:
                raise RuntimeError("The converted DOCX differs from the registered final DOCX.")
            if hashlib.sha256(pdf).hexdigest() != result["part_request"]["pdf"]["sha256"]:
                raise RuntimeError("The registered PDF differs from LibreOffice output.")
            with fitz.open(stream=pdf, filetype="pdf") as document:
                appendix = document[-1]
                if (
                    document.page_count < 2
                    or "Визуално приложение към заявката" not in appendix.get_text()
                    or not appendix.get_images()
                ):
                    raise RuntimeError("LibreOffice PDF lost the visual appendix.")
    finally:
        part_request_documents.convert_docx_to_pdf = original
    print("part_visual_appendix_libreoffice=passed")


if __name__ == "__main__":
    main()
